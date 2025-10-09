# 🤖 WallaScraper

Bot de alertas de Wallapop con integración de Telegram. Permite buscar artículos automáticamente y recibir notificaciones en tu chat.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)  
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)  
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://core.telegram.org/bots)

---

## ✨ Características

- Búsquedas programadas de artículos
- Notificaciones por Telegram (detalladas o en bulk)
- Soporte de filtros personalizados
- Compatible con Playwright + Chromium
- Configuración de token vía `.env` o `launch.bat`

---

## 🛠 Requisitos

- Python 3.10+
- Telegram Bot API Token de BotFather

---

## ⚡ Instalación

1. Clonar el repositorio:

```bash
git clone https://github.com/alejamt00/WallaScraper.git
cd WallaScraper
```

2. Configurar entorno y dependencias usando `launch.bat` (Windows)

---

## 🚀 Uso

- Ejecutar `launch.bat` y seguir el menú:
  - Setup completo
  - Arrancar bot
  - Resetear dependencias
- El token de Telegram se puede configurar la primera vez o cambiar antes de iniciar el bot.

---

## 📂 Estructura de proyecto

```
WallaScraper/
 ├─ src/
 │   ├─ bot.py
 │   ├─ scheduler.py
 │   ├─ wallapop.py
 │   ├─ db.py
 │   └─ inspect_db.py
 ├─ launch.bat
 ├─ requirements.txt
 └─ README.md
```

---

## 📄 Licencia

MIT License

---

## ℹ️ About

Scraper para Wallapop y avisos a través de bot de Telegram.
