from app import create_app, db
from app.models.profile import Profile
from app.models.company import Company
from app.models.post import Post
from app.models.signal import Signal
import random
import uuid
from datetime import datetime, timedelta

def seed_dummy_signals():
    app = create_app()
    with app.app_context():
        print("Starting dummy signal generation...")
        profiles = list(Profile.query.all())  # List to iterate
        
        if not profiles:
            print("No profiles found. Please import leads first.")
            return

        tenant_id = profiles[0].tenant_id # Assume single tenant for simplicity
        
        counts = {"companies": 0, "posts": 0, "signals": 0}
        
        for profile in profiles:
            # Skip if 30% chance or no company name
            if not profile.company_name or random.random() > 0.7:
                continue

            # 1. Get or Create Company
            company = Company.query.filter_by(
                tenant_id=tenant_id, 
                name=profile.company_name
            ).first()
            
            if not company:
                company = Company(
                    tenant_id=tenant_id,
                    name=profile.company_name,
                    linkedin_url=f"https://linkedin.com/company/{profile.company_name.lower().replace(' ', '-')}"
                )
                db.session.add(company)
                db.session.flush() # Get ID
                counts["companies"] += 1
            
            # 2. Create Signals
            num_signals = random.randint(1, 4)
            signal_types = ['company_news', 'linkedin_activity', 'product_launch', 'career_move']
            
            for _ in range(num_signals):
                stype = random.choice(signal_types)
                created_at = datetime.utcnow() - timedelta(days=random.randint(1, 45))
                
                post = None
                if stype in ['company_news', 'product_launch', 'linkedin_activity']:
                    # Create a dummy Post
                    post_text = ""
                    if stype == "company_news":
                        post_text = f"{profile.company_name} is excited to announce a new strategic partnership to expand our global reach."
                    elif stype == "product_launch":
                        post_text = f"Introducing our latest innovation: The {profile.company_name} AI Platform. Revolutionizing the industry."
                    elif stype == "linkedin_activity":
                         post_text = f"Great discussion on the future of {profile.industry or 'tech'}! #innovation #growth"
                         
                    post = Post(
                        tenant_id=tenant_id,
                        company_id=company.company_id,
                        source_url=f"https://linkedin.com/posts/{uuid.uuid4()}",
                        post_text=post_text,
                        post_date=created_at.date(),
                        score=random.randint(70, 95),
                        ai_judgement="relevant"
                    )
                    db.session.add(post)
                    db.session.flush()
                    counts["posts"] += 1

                # Create Signal
                sig = Signal(
                    tenant_id=tenant_id,
                    signal_type=stype,
                    company_id=company.company_id,
                    profile_id=profile.profile_id,
                    post_id=post.post_id if post else None,
                    score=random.randint(60, 99),
                    keywords=f"dummy, {stype}",
                    created_at=created_at,
                    signal_metadata={
                        "source": "dummy_script",
                        "type": "launch" if stype == "product_launch" else None,
                        "new_role": profile.job_title if stype == 'career_move' else None
                    }
                )
                db.session.add(sig)
                counts["signals"] += 1
        
        db.session.commit()
        print(f"Done! Created: {counts}")

if __name__ == "__main__":
    seed_dummy_signals()
