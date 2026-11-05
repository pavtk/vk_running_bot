import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import User
from app.settings import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(engine, expire_on_commit=False)


def get_or_create_user(user_id, first_name, last_name, age, sex, city_id):
    """Возвращает существующего пользователя или создаёт нового.

    Args:
        user_id: VK ID пользователя
        first_name: имя
        last_name: фамилия
        age: возраст (может быть None если скрыт в профиле)
        sex: пол (1 — женский, 2 — мужской)
        city_id: город (может быть None если не указан)

    Returns:
        User: объект пользователя из БД
    """
    with Session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                age=age,
                sex=sex,
                city_id=city_id,
            )
            session.add(user)
            session.commit()
            logger.info("Создан новый пользователь vk_id=%s", user_id)
        else:
            logger.debug("Пользователь vk_id=%s уже существует", user_id)
        return user