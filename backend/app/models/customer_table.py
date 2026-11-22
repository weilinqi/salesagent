"""Dynamic customer table models.

Each upload keeps its own inferred schema. No global customer columns are
imposed, so different sales teams can keep their familiar layout.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.database import Base


class CustomerTable(Base):
    __tablename__ = "customer_tables"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    source_filename = Column(String(255), nullable=True)
    source_sheet = Column(String(255), nullable=True)
    header_row = Column(Integer, nullable=True)
    columns = Column(JSON, default=list)
    row_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    rows = relationship(
        "CustomerTableRow",
        back_populates="table",
        cascade="all, delete-orphan",
        order_by="CustomerTableRow.position",
    )


class CustomerTableRow(Base):
    __tablename__ = "customer_table_rows"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    table_id = Column(
        String(36),
        ForeignKey("customer_tables.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position = Column(Integer, nullable=False)
    cells = Column(JSON, default=dict)
    original_cells = Column(JSON, default=dict)
    uncertain = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    table = relationship("CustomerTable", back_populates="rows")