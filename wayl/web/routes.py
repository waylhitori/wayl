
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from ..services.agent_service import AgentService
from ..services.payment_service import PaymentService
from .dependencies import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="wayl/web/templates")

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
   return templates.TemplateResponse("index.html", {"request": request})

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
   request: Request,
   current_user = Depends(get_current_user),
   agent_service: AgentService = Depends(),
   payment_service: PaymentService = Depends()
):
   agents = await agent_service.list_agents(current_user.id)
   token_info = await payment_service.get_token_info(current_user.id)
   return templates.TemplateResponse(
       "dashboard.html",
       {
           "request": request,
           "user": current_user,
           "agents": agents,
           "token_info": token_info
       }
   )