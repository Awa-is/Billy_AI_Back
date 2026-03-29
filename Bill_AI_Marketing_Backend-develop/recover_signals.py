from app import create_app
from app.models.tenant import Tenant
from app.tasks.signal_tasks import process_signals_and_emails_task, generate_emails_from_signals_task

def recover():
    app = create_app()
    with app.app_context():
        tenants = Tenant.query.all()
        print(f"Found {len(tenants)} tenants. Triggering signal detection and email generation recovery...")
        for t in tenants:
            # 1. Detect signals from analyzed posts
            process_signals_and_emails_task.delay(t.tenant_id)
            # 2. Generate emails for existing signals (in case step 1 failed midway previously)
            generate_emails_from_signals_task.delay(t.tenant_id)
            print(f"Queued signal detection and email generation tasks for tenant {t.tenant_id}")

if __name__ == "__main__":
    recover()
