FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12.9-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1

RUN pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY pyproject.toml ./
RUN uv pip install --system --index-url https://pypi.tuna.tsinghua.edu.cn/simple -e .

COPY app ./app
RUN mkdir -p /app/cache

EXPOSE 8000
CMD ["python", "-m", "app.main"]