# Deployment Guide

This project is ready to be deployed in a split setup:

- Netlify: hosts the frontend pages
- Render: hosts the Flask backend API

## 1. Push the project to GitHub

1. Create a GitHub repository.
2. Upload the project files.
3. Make sure these files are included:
   - index.html
   - pages/
   - backend/
   - requirements.txt
   - api_server.py
   - Procfile
   - render.yaml
   - runtime.txt

## 2. Deploy the backend on Render

1. Open Render.
2. Click New -> Web Service.
3. Connect your GitHub repository.
4. Choose the project repo.
5. Use these settings:
   - Build Command: pip install -r requirements.txt
   - Start Command: python api_server.py

### Environment variables
Add these in the Render dashboard:

- PORT = 10000
- FIREBASE_DATABASE_URL = https://smartwaiter-c9a2e-default-rtdb.firebaseio.com

Optional:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

## 3. Verify the backend

After deployment, open:

- https://YOUR_RENDER_APP.onrender.com/health

It should return JSON with a status of ok.

## 4. Deploy the frontend on Netlify

1. Open Netlify.
2. Click Add new site -> Import an existing project.
3. Connect the same GitHub repo.
4. Set the publish directory to the project root.
5. Deploy.

## 5. Connect the frontend to the backend

Replace any localhost or 127.0.0.1 API URLs with your Render backend URL.

Example:

- Before: http://127.0.0.1:5001/health
- After: https://YOUR_RENDER_APP.onrender.com/health

## 6. Notes

- Netlify cannot run the Python Flask backend directly.
- The frontend can be hosted on Netlify.
- The backend must be hosted separately on Render or another Python host.
