"""
Signal Detection Service

Detects signals from analyzed posts based on configurable criteria:
- AI score > threshold (default 80)
- AI judgement matches signal types (product_launch, company_news)
- Post contains relevant keywords
- Post is recent (within 7 days)
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.extensions import db
from app.models.post import Post
from app.models.signal import Signal
from app.models.company import Company
from app.models.profile import Profile
import logging
import re

logger = logging.getLogger(__name__)

# Default signal detection keywords
SIGNAL_KEYWORDS = {
    'product_launch': [
        'launch', 'announce', 'introducing', 'new product', 'release', 'unveil',
        'debut', 'rollout', 'premiere', 'available now', 'coming soon'
    ],
    'company_news': [
        'milestone', 'achievement', 'partnership', 'expansion', 'growth',
        'funding', 'investment', 'acquisition', 'merger', 'award', 'recognition',
        'expansion', 'new office', 'hiring', 'team growth'
    ]
}

# Default threshold for signal detection
DEFAULT_SCORE_THRESHOLD = 80

# Default days for recent posts
DEFAULT_RECENT_DAYS = 7


def get_signal_threshold(tenant_id: str) -> int:
    """Get signal detection threshold for tenant (default 80)."""
    from app.models.tenant_setting import TenantSetting
    
    setting = TenantSetting.query.filter_by(
        tenant_id=tenant_id,
        key='signal_score_threshold'
    ).first()
    
    if setting and setting.value:
        try:
            return int(setting.value)
        except ValueError:
            pass
    
    return DEFAULT_SCORE_THRESHOLD


def get_recent_days(tenant_id: str) -> int:
    """Get recent days threshold for tenant (default 7)."""
    from app.models.tenant_setting import TenantSetting
    
    setting = TenantSetting.query.filter_by(
        tenant_id=tenant_id,
        key='signal_recent_days'
    ).first()
    
    if setting and setting.value:
        try:
            return int(setting.value)
        except ValueError:
            pass
    
    return DEFAULT_RECENT_DAYS


def extract_keywords(text: str, signal_type: str) -> List[str]:
    """Extract relevant keywords from text for given signal type."""
    if not text:
        return []
    
    text_lower = text.lower()
    keywords = SIGNAL_KEYWORDS.get(signal_type, [])
    found_keywords = []
    
    for keyword in keywords:
        if keyword.lower() in text_lower:
            found_keywords.append(keyword)
    
    return found_keywords


def is_post_recent(post: Post, recent_days: int) -> bool:
    """Check if post is within recent days threshold."""
    if not post.post_date:
        # If no post_date, check created_at
        if post.created_at:
            days_ago = (datetime.utcnow() - post.created_at).days
            return days_ago <= recent_days
        return False
    
    days_ago = (datetime.utcnow().date() - post.post_date).days
    return days_ago <= recent_days


def detect_signal_from_post(post: Post, tenant_id: str) -> Optional[Signal]:
    """
    Detect signal from a single analyzed post.
    
    Criteria:
    - AI score > threshold (default 80)
    - AI judgement matches signal type (product_launch, company_news)
    - Post contains relevant keywords
    - Post is recent (within 7 days)
    
    Returns:
        Signal object if detected, None otherwise
    """
    # Check if post has been analyzed
    if not post.analyzed_at or not post.ai_judgement:
        logger.debug(f"Post {post.post_id} not analyzed yet")
        return None
    
    # Check if signal already exists for this post
    existing_signal = Signal.query.filter_by(
        tenant_id=tenant_id,
        post_id=post.post_id,
        signal_type=post.ai_judgement
    ).first()
    
    if existing_signal:
        logger.debug(f"Signal already exists for post {post.post_id}")
        return None
    
    # Get thresholds
    score_threshold = get_signal_threshold(tenant_id)
    recent_days = get_recent_days(tenant_id)
    
    # Check score threshold
    if not post.score or post.score < score_threshold:
        logger.debug(f"Post {post.post_id} score {post.score} below threshold {score_threshold}")
        return None
    
    # Check signal type
    signal_type = post.ai_judgement
    if signal_type not in ['product_launch', 'company_news']:
        logger.debug(f"Post {post.post_id} judgement '{signal_type}' is not a signal type")
        return None
    
    # Check if post is recent
    if not is_post_recent(post, recent_days):
        logger.debug(f"Post {post.post_id} is not recent (older than {recent_days} days)")
        return None
    
    # Extract keywords
    keywords = extract_keywords(post.post_text or '', signal_type)
    
    # Create signal
    signal = Signal(
        tenant_id=tenant_id,
        signal_type=signal_type,
        post_id=post.post_id,
        company_id=post.company_id,
        score=post.score,
        keywords=','.join(keywords) if keywords else None,
        signal_metadata={
            'post_text': post.post_text[:500] if post.post_text else None,  # Store first 500 chars
            'post_date': post.post_date.isoformat() if post.post_date else None,
            'analyzed_at': post.analyzed_at.isoformat() if post.analyzed_at else None
        }
    )
    
    db.session.add(signal)
    
    try:
        db.session.commit()
        logger.info(f"Signal detected: {signal.signal_id} for post {post.post_id}, type={signal_type}, score={post.score}")
        return signal
    except Exception as e:
        logger.error(f"Failed to create signal for post {post.post_id}: {e}")
        db.session.rollback()
        return None


def detect_signals_from_analyzed_posts(tenant_id: str, limit: Optional[int] = None) -> List[Signal]:
    """
    Detect signals from all recently analyzed posts for a tenant.
    
    Args:
        tenant_id: Tenant ID
        limit: Optional limit on number of posts to check
        
    Returns:
        List of detected Signal objects
    """
    recent_days = get_recent_days(tenant_id)
    cutoff_date = datetime.utcnow() - timedelta(days=recent_days)
    
    # Query posts that:
    # 1. Belong to tenant
    # 2. Have been analyzed
    # 3. Have score >= threshold
    # 4. Have signal-type judgement (product_launch, company_news)
    # 5. Are recent
    score_threshold = get_signal_threshold(tenant_id)
    
    query = Post.query.filter(
        Post.tenant_id == tenant_id,
        Post.analyzed_at.isnot(None),
        Post.ai_judgement.in_(['product_launch', 'company_news']),
        Post.score >= score_threshold,
        Post.post_date >= cutoff_date.date() if cutoff_date else True
    )
    
    if limit:
        query = query.limit(limit)
    
    posts = query.all()
    
    detected_signals = []
    for post in posts:
        signal = detect_signal_from_post(post, tenant_id)
        if signal:
            detected_signals.append(signal)
    
    logger.info(f"Detected {len(detected_signals)} signals from {len(posts)} analyzed posts for tenant {tenant_id}")
    
    return detected_signals

