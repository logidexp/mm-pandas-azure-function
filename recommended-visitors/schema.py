from typing import List, Any, Dict
from pydantic import BaseModel

class VisitorRecommendation(BaseModel):
    visitor_email: str
    visitor_details: Dict[str, Any] = {}
    score: float

class VisitorRecommendations(BaseModel):
    event: int
    exhibitor_id: int
    visitors: List[VisitorRecommendation]