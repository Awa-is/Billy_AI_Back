from app import create_app, db
from sqlalchemy import text

def audit():
    app = create_app()
    with app.app_context():
        print("=== AUDIT START ===")
        
        # 1. Tenants
        print("--- Tenant IDs in Profiles ---")
        rows = db.session.execute(text("SELECT tenant_id, COUNT(*) FROM profiles GROUP BY tenant_id")).fetchall()
        t_profiles = [r[0] for r in rows]
        for r in rows: print(f"{r[0]}: {r[1]}")
        
        print("--- Tenant IDs in Signals ---")
        rows = db.session.execute(text("SELECT tenant_id, COUNT(*) FROM signals GROUP BY tenant_id")).fetchall()
        t_signals = [r[0] for r in rows]
        for r in rows: print(f"{r[0]}: {r[1]}")
        
        # 2. Join Check
        print("--- Join Consistency ---")
        # Check simple join count without tenant filter
        rows = db.session.execute(text("SELECT COUNT(*) FROM profiles p JOIN signals s ON p.profile_id = s.profile_id")).fetchall()
        print(f"Total Matches (Profile-Signal): {rows[0][0]}")
        
        # Check if Tenant IDs match in joined rows
        rows = db.session.execute(text("SELECT COUNT(*) FROM profiles p JOIN signals s ON p.profile_id = s.profile_id WHERE p.tenant_id = s.tenant_id")).fetchall()
        print(f"Matches with Same Tenant: {rows[0][0]}")
        
        target_tenant = "1c8b8696-0372-4f23-b74c-fd7f44d2f3c8"
        print(f"--- Sampling Specific User Tenant {target_tenant} ---")
        rows = db.session.execute(text(f"SELECT COUNT(*) FROM profiles WHERE tenant_id = '{target_tenant}'")).fetchall()
        print(f"Profile Count: {rows[0][0]}")
        rows = db.session.execute(text(f"SELECT COUNT(*) FROM signals WHERE tenant_id = '{target_tenant}'")).fetchall()
        print(f"Signal Count: {rows[0][0]}")
        
        # Check join for this tenant
        rows = db.session.execute(text(f"SELECT COUNT(*) FROM profiles p JOIN signals s ON p.profile_id = s.profile_id WHERE p.tenant_id = '{target_tenant}' AND s.tenant_id = '{target_tenant}'")).fetchall()
        print(f"Valid Joined Signals: {rows[0][0]}")

        print("=== AUDIT END ===")

if __name__ == "__main__":
    audit()
