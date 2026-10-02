import os
import json
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()

# Configurações de Logs
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Chaves de API obtidas de forma segura das variáveis de ambiente
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Groq(api_key=GROQ_API_KEY)
MODELO_CHAT = "openai/gpt-oss-120b"
MODELO_STT = "whisper-large-v3-turbo"  # Modelo de Transcrição de Áudio

user_sessions = {}

def carregar_memoria(user_id, idioma):
    pasta = os.path.join("dados", f"user_{user_id}", idioma.lower().replace(" ", "_"))
    os.makedirs(pasta, exist_ok=True)
    caminho_arquivo = os.path.join(pasta, "srs_memoria.json")
    
    if os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            return json.load(f), caminho_arquivo
    return {"itens_em_revisao": [], "historico_sessoes": 0}, caminho_arquivo

def salvar_memoria(caminho_arquivo, memoria):
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)

def obter_system_prompt(idioma_alvo, memoria):
    itens_srs = memoria.get("itens_em_revisao", [])
    contexto_srs = json.dumps(itens_srs, ensure_ascii=False) if itens_srs else "Nenhum item registrado ainda."

    return f"""
# SYSTEM PROMPT: AI LANGUAGE TUTOR (Hermes Agent)

## PERSONA & OBJETIVO
Você é um tutor de idiomas especialista em aquisição natural de linguagem. Seu papel é atuar como um parceiro de conversa natural, aplicando o Método Socrático e a hipótese do Comprehensible Input (nível i+1). 

O idioma alvo desta sessão é EXCLUSIVAMENTE: {idioma_alvo}.
Adapte todas as respostas da conversa e exemplos para o {idioma_alvo}.

## MEMÓRIA SRS DO ALUNO (ITENS A REVISAR)
Os seguintes itens foram praticados anteriormente e devem ser reintroduzidos sutilmente em novos contextos de diálogo:
{contexto_srs}

## DIRETRIZES DE COMUNICAÇÃO (REGRAS INVIOLÁVEIS)
1. ZERO METALINGUAGEM GRAMATICAL:
   - NUNCA use termos técnicos gramaticais.
   - Refira-se aos elementos apenas como "a forma de dizer X" ou "a expressão para Y".

2. MÉTODO SOCRÁTICO & APRENDIZADO INDUTIVO:
   - NUNCA dê a resposta direta quando o aluno errar. Faça perguntas orientadoras.

3. RETRIEVAL PRACTICE:
   - Reintroduza os itens SRS em situações de diálogo inéditas.

4. REGISTRO DE NOVOS APRENDIZADOS:
   - Se o aluno aprender algo novo, inclua no final: [NOVO_ITEM: {{"termo": "exemplo", "contexto": "frase em contexto"}}]

## ESTRUTURA DAS RESPOSTAS
1. 🗣️ CONVERSA FLUÍDA (Em {idioma_alvo})
2. 💡 PROVOCAÇÃO SOCRÁTICA / RETRIEVAL
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Eu sou o seu Tutor Socrático de Idiomas.\n\n"
        "Você pode falar comigo digitando texto ou **enviando mensagens de áudio/voz**!\n\n"
        "Para começar, defina o idioma: `/idioma Ingles` ou `/idioma Italiano`",
        parse_mode="Markdown"
    )

async def definir_idioma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Por favor, especifique o idioma. Exemplo: `/idioma Ingles`", parse_mode="Markdown")
        return

    idioma = " ".join(context.args).strip().capitalize()
    memoria, caminho_memoria = carregar_memoria(user_id, idioma)
    memoria["historico_sessoes"] += 1

    system_prompt = obter_system_prompt(idioma, memoria)
    
    user_sessions[user_id] = {
        "idioma": idioma,
        "memoria": memoria,
        "caminho_memoria": caminho_memoria,
        "messages": [{"role": "system", "content": system_prompt}]
    }

    await update.message.reply_text(
        f"✅ Sessão #{memoria['historico_sessoes']} iniciada para *{idioma}*!\n"
        f"Pode enviar mensagens de texto ou **áudios gravados** no Telegram.",
        parse_mode="Markdown"
    )

async def responder_tutor(user_id, update, user_text):
    session = user_sessions[user_id]
    session["messages"].append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=MODELO_CHAT,
            messages=session["messages"],
            temperature=0.3
        )
        bot_reply = response.choices[0].message.content

        if "[NOVO_ITEM:" in bot_reply:
            try:
                inicio = bot_reply.find("[NOVO_ITEM:") + len("[NOVO_ITEM:")
                fim = bot_reply.find("]", inicio)
                str_item = bot_reply[inicio:fim].strip()
                item_json = json.loads(str_item)
                
                session["memoria"]["itens_em_revisao"].append(item_json)
                salvar_memoria(session["caminho_memoria"], session["memoria"])
                
                bot_reply = bot_reply[:bot_reply.find("[NOVO_ITEM:")].strip()
            except Exception:
                pass

        session["messages"].append({"role": "assistant", "content": bot_reply})
        await update.message.reply_text(bot_reply)

    except Exception as e:
        await update.message.reply_text(f"❌ Erro na API Groq: {e}")

async def processar_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await update.message.reply_text("Defina o idioma antes com `/idioma NomeDoIdioma`.", parse_mode="Markdown")
        return

    await responder_tutor(user_id, update, update.message.text)

async def processar_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await update.message.reply_text("Defina o idioma antes com `/idioma NomeDoIdioma`.", parse_mode="Markdown")
        return

    # Baixar arquivo de voz enviado pelo usuário
    audio_file = await context.bot.get_file(update.message.voice.file_id)
    caminho_audio = f"voice_{user_id}.ogg"
    await audio_file.download_to_drive(caminho_audio)

    await update.message.reply_text("🎙️ *Ouvindo o seu áudio...*", parse_mode="Markdown")

    try:
        # Transcrever áudio via Whisper na API do Groq
        with open(caminho_audio, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(caminho_audio, file.read()),
                model=MODELO_STT,
                response_format="text"
            )

        texto_transcrito = str(transcription).strip()
        await update.message.reply_text(f"🗣️ *Você disse:* \"{texto_transcrito}\"", parse_mode="Markdown")

        # Apagar o arquivo temporário
        if os.path.exists(caminho_audio):
            os.remove(caminho_audio)

        # Enviar transcrição para o Tutor
        await responder_tutor(user_id, update, texto_transcrito)

    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao processar áudio com Whisper: {e}")
        if os.path.exists(caminho_audio):
            os.remove(caminho_audio)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("idioma", definir_idioma))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), processar_mensagem))
    app.add_handler(MessageHandler(filters.VOICE, processar_audio))

    print("🤖 Bot do Telegram com suporte a ÁUDIO (Whisper) iniciado...")
    app.run_polling()
