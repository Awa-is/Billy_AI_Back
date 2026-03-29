from app import create_app
import os

app = create_app()

if __name__ == '__main__':
    # Force logging to stdout
    import logging
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='[FLASK %(levelname)s] %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    app.logger.setLevel(logging.INFO)
    
    # Print DB Connection Info
    db_url = app.config.get('SQLALCHEMY_DATABASE_URI', 'Not Set')
    if '@' in db_url:
        # Mask password
        prefix = db_url.split('@')[0]
        suffix = db_url.split('@')[1]
        proto = prefix.split(':')[0]
        user = prefix.split(':')[1].split('//')[1]
        masked_url = f"{proto}://{user}:****@{suffix}"
        logging.info(f"Connecting to Database: {masked_url}")
    else:
        logging.info(f"Connecting to Database: {db_url}")



    # Development
    app.run(debug=True, port=5000)
else:
    # Production (Gunicorn)
    pass