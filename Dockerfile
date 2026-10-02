# Usa uma imagem Python oficial e leve
FROM python:3.11-slim

# Instala o FFmpeg (necessário para processar áudios do Telegram)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Define o diretório de trabalho dentro do container
WORKDIR /app

# Copia os arquivos de dependências
COPY requirements.txt .

# Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código da aplicação
COPY . .

# Comando para iniciar o bot
CMD ["python3", "bot_telegram.py"]
