FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install --root-user-action=ignore -r requirements.txt
COPY *.py ./
COPY vendors ./vendors
VOLUME /data
CMD ["python", "main.py"]
