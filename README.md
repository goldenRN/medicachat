# SOS Medica AI Chatbot Demo

Python backend + Next.js frontend-тэй, role-based upload болон chat history persistence-тэй chatbot demo.

## Ажиллуулах

Backend:

```bash
npm start
```

Frontend:

```bash
npm run frontend
```

URLs:

```text
Frontend (Next.js): http://127.0.0.1:3000
Backend API/static: http://127.0.0.1:4173
```

## AI provider холбох

1. `.env.example`-ийг `.env` болгож хуулна
2. Gemini ашиглах бол `GEMINI_API_KEY` дээр key-гээ хийнэ
3. хүсвэл `AI_PROVIDER=gemini` гэж зааж өгнө
4. model-оо хүсвэл солино
5. server-ээ restart хийнэ

Жишээ:

```bash
cp .env.example .env
```

Gemini default model нь `gemini-2.5-flash`. OpenAI default model нь `gpt-5`.

Provider горимууд:

- `AI_PROVIDER=auto`: эхлээд Gemini key байвал Gemini, үгүй бол OpenAI, үгүй бол local fallback
- `AI_PROVIDER=gemini`: зөвхөн Gemini ашиглана
- `AI_PROVIDER=openai`: зөвхөн OpenAI ашиглана
- `AI_PROVIDER=local`: AI API дуудахгүй, зөвхөн local fallback

Key байхгүй үед chatbot local fallback logic-оороо ажиллана.

## Юу байгаа вэ

- Next.js App Router frontend
- Separate `/login` and `/chat` pages
- Proxy API route from Next.js to Python backend
- Python backend API
- Gemini API integration with local fallback
- OpenAI Responses API integration with local fallback
- Role-based login (`admin`, `staff`)
- Admin file upload
- Persisted document knowledge base
- Saved chat histories
- Seed knowledge base
- Quick prompt buttons
- Local `.txt`, `.md`, `.json`, `.csv`, `.pdf` upload

## Demo account

- `admin@sosmedica.mn / admin123`
- `staff@sosmedica.mn / staff123`

## Persistence

- SQLite database: `data/app.db`
- Uploaded files: `data/uploads`
- Legacy migration backups: `data/users.json`, `data/documents.json`, `data/histories.json`

## Frontend structure

- `web/app`: Next.js pages and API proxy route
- `web/components`: login/chat UI components
- `web/lib`: session and fetch helpers
- `web/app/globals.css`: shared app styles

## Backend structure

- `app.py`: Python HTTP server entrypoint
- `backend/http_server.py`: auth, SQLite persistence, upload, API routes
- `backend/chat_logic.py`: retrieval, follow-up, aggregate logic
- `backend/gemini_service.py`: Gemini generateContent integration
- `backend/openai_service.py`: OpenAI Responses API integration
- `backend/ai_service.py`: active provider selection
- `data/app.db`: SQLite database
