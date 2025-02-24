from typing import List, Any, Dict
from pydantic import BaseModel

class ExhibitorRecommendation(BaseModel):
    exhibitor_id: int
    exhibitor_details: Dict[str, Any] = {}
    score: float

class ExhibitorRecommendations(BaseModel):
    event: int
    visitor_email: str
    exhibitors: List[ExhibitorRecommendation]