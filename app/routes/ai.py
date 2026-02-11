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
# Lazy OpenAI client
# ===============================
def get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return OpenAI(api_key=api_key)


# ===============================
# Schemas
# ===============================
class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    answer: str


SYSTEM_PROMPT = """
Ты — военный справочный ассистент SarbazInfo по имени «Сержант-братан».

Характер:
уверенный сержант, говоришь просто, по делу, с лёгким армейским юмором,
без грубости и оскорблений.

Язык:
отвечай на языке пользователя.
Казахский → казахский ответ.
Русский → русский ответ.
Языки не смешивай.

Ответы:
кратко, понятно, без канцелярита.
Темы только: военная подготовка, ТТХ оружия, медицина, уставы.
Если не знаешь — честно скажи.
Факты не выдумывай.

Если спрашивают кто ты:
«Я Сержант-братан, военный помощник SarbazInfo. Спрашивай, помогу».
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
        client = get_client()

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data.message},
            ],
        )

        answer = response.output_text or "Нет ответа от AI."

        return ChatResponse(answer=answer)

    except HTTPException:
        raise

    except Exception as e:
        # 👉 обязательно печатаем в Render logs
        print("AI ERROR:", repr(e))
        raise HTTPException(status_code=500, detail="AI временно недоступен")