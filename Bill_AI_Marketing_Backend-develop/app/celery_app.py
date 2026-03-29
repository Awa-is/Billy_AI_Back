from celery import Celery


celery_app = Celery(__name__)


def init_celery(app):
    """
    Bind Celery to the current Flask app context so tasks can use database/session.
    """
    broker_url = app.config.get('CELERY_BROKER_URL')
    result_backend = app.config.get('CELERY_RESULT_BACKEND')

    celery_app.conf.update(
        broker_url=broker_url,
        result_backend=result_backend,
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='UTC',
    )

    class ContextTask(celery_app.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return super().__call__(*args, **kwargs)

    celery_app.Task = ContextTask
    return celery_app

