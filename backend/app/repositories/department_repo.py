from app.models import Department
from app.repositories.base import BaseRepository


class DepartmentRepository(BaseRepository):
    model = Department
