from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Like(Base):
    __tablename__ = "post_likes"

    # The composite key prevents duplicate likes, including concurrent requests.
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True,
    )
    post: Mapped["Post"] = relationship(back_populates="likes")
    user: Mapped["User"] = relationship(back_populates="likes")
