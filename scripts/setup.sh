
#!/bin/bash
set -e

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup database
python -c "from wayl.db.models import Base; from sqlalchemy import create_engine; engine = create_engine('postgresql://wayl:wayl@localhost/wayl'); Base.metadata.create_all(engine)"

# Download initial model
mkdir -p models
wget -P models/ https://huggingface.co/deepseek-ai/deepseek-7b/resolve/main/model.bin