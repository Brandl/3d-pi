FROM docker.io/library/node:24-alpine@sha256:333f6b3eca25980d5682c26207665b93c9417786b21760b2764d5821d9704c8a AS viewer
WORKDIR /build/web
COPY cad/casting_box.py cad/captured_base.py /build/cad/
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

FROM docker.io/library/python:3.12-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 libcom-err2 libp11-kit0 fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.16
WORKDIR /opt/cad
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY cad/ ./cad/
COPY examples/ ./examples/
COPY --from=viewer /build/web/dist ./web/dist
RUN useradd --uid 1000 --create-home cad && chmod -R a+rX /opt/cad
ENV PATH="/opt/cad/.venv/bin:$PATH" CAD_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
USER 1000:1000
EXPOSE 8765 8767
CMD ["python", "-m", "uvicorn", "cad.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8765"]
