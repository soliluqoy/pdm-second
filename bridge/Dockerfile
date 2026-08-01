FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bridge source (codec8e.py, fmc_bridge.py, avl_map.<model>.json)
COPY . .

# Raw TCP listener for Teltonika devices (FMC001 + FMC150)
EXPOSE 5123

CMD ["python", "fmc_bridge.py"]
