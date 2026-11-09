"""
SQLAlchemy ORM-модели graph-абстракции: Entity (с иерархией) + Link (типизированный).

Иерархия (issue #13): Entity.parent_id, relationships parent/children.
Типы связей (issue #14): Link.type ∈ contains|depends|relates|blocks|triggers.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship

from core.symbio_hive.links import LinkType, normalize_link_type


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    meta = Column(Text, default="{}")
    # Иерархия (issue #13)
    parent_id = Column(Integer, ForeignKey("entities.id"), nullable=True, index=True)

    # Связи
    source_links = relationship(
        "Link",
        back_populates="source",
        foreign_keys="Link.source_id",
        cascade="all, delete-orphan",
    )
    target_links = relationship(
        "Link",
        back_populates="target",
        foreign_keys="Link.target_id",
        cascade="all, delete-orphan",
    )
    parent = relationship(
        "Entity",
        foreign_keys=[parent_id],
        remote_side=[id],
        back_populates="children",
    )
    children = relationship(
        "Entity",
        foreign_keys=[parent_id],
        back_populates="parent",
    )

    @property
    def has_children(self) -> bool:
        return bool(self.children)

    def to_dict(self, include_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "meta": self.meta or "{}",
            "parent_id": self.parent_id,
            "has_children": bool(self.children),
        }
        if include_children:
            data["children"] = [child.to_dict() for child in self.children]
        return data

    def to_tree_node(self) -> dict:
        """Узел дерева с вложенными детьми."""
        return {
            "id": self.id,
            "name": self.name,
            "meta": self.meta or "{}",
            "parent_id": self.parent_id,
            "has_children": bool(self.children),
            "children": [child.to_tree_node() for child in self.children],
        }


class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("entities.id"), nullable=False, index=True)
    target_id = Column(Integer, ForeignKey("entities.id"), nullable=False, index=True)
    # Тип связи (issue #14)
    type = Column(String(20), nullable=False, default=LinkType.RELATES.value, index=True)
    meta = Column(Text, default="{}")

    source = relationship("Entity", foreign_keys=[source_id], back_populates="source_links")
    target = relationship("Entity", foreign_keys=[target_id], back_populates="target_links")

    # Уникальность связи с учётом типа (issue #14)
    __table_args__ = (
        Index("ix_links_source_target_type", "source_id", "target_id", "type", unique=True),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "type": normalize_link_type(self.type),
            "meta": self.meta or "{}",
        }


class LLMUsage(Base):
    """Учёт обращений к LLM-провайдерам (issue #9, задача 3: cost tracking)."""

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(UTC), index=True)
    provider = Column(String(50), nullable=False, index=True)
    action = Column(String(50), default="unknown")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    success = Column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "provider": self.provider,
            "action": self.action,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "success": self.success,
        }
