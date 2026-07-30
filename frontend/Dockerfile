FROM node:22-alpine

WORKDIR /app

# Copy package files and install dependencies
COPY package.json package-lock.json* ./
RUN npm install

# Copy source (also mounted as volume for dev hot-reload)
COPY . .

# Expose Vite dev server port
EXPOSE 5173

# Start Vite dev server with host binding for Docker
CMD ["npm", "run", "dev"]