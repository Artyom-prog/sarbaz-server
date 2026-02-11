import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from openai import OpenAI

from app.routes.auth import get_current_user
from app.db import get_db
from app.services.ai_limits import check_and_increment_usage


router = APIRouter(prefix="/api/ai", tags=["AI"])


# ===============================
# OpenAI client
# ===============================
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=api_key)


# ===============================
# Schemas
# ===============================
class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str


# ===============================
# SYSTEM PROMPT
# ===============================
SYSTEM_PROMPT = """
Ты — военный справочный ассистент приложения SarbazInfo.

Правила:
- Отвечай кратко и понятно.
- Используй простой язык.
- Отвечай только по военной подготовке, ТТХ оружия, медицине и уставам.
- Если не знаешь — честно скажи, что информации нет.
- Не выдумывай.
"""


# ===============================
# CHAT ENDPOINT
# ===============================
@router.post("/chat", response_model=ChatResponse)
async def chat_ai(
    data: ChatRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 🔒 проверка лимита
    allowed = check_and_increment_usage(db, user)
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Дневной лимит 5 запросов исчерпан. Оформите премиум.",
        )

    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data.message},
            ],
            temperature=0.3,
            max_tokens=500,
        )

        answer = completion.choices[0].message.content

        return ChatResponse(answer=answer)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))