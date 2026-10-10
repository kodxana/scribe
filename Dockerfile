FROM python:3.13-bookworm@sha256:073ffebb96ae4d0ed73ccad59f08c47bd84af8a79f5258130f8458ac50ad9ff4

STOPSIGNAL SIGINT

ARG user=lbry
ARG db_dir=/database
ARG projects_dir=/home/$user

ARG DOCKER_TAG
ARG DOCKER_COMMIT=docker
ENV DOCKER_TAG=$DOCKER_TAG DOCKER_COMMIT=$DOCKER_COMMIT

RUN apt-get update && \
    apt-get -y --no-install-recommends install \
      wget \
      tar unzip \
      build-essential libssl-dev libffi-dev \
      automake libtool \
      pkg-config && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -g 999 $user && useradd -m -u 999 -g $user $user
RUN mkdir -p $db_dir
RUN chown -R $user:$user $db_dir

COPY . $projects_dir
RUN chown -R $user:$user $projects_dir

USER $user
WORKDIR $projects_dir
RUN python -m pip install pip==26.2.1
RUN python -m pip install -e . && python -m pip check
RUN python scripts/set_build.py
RUN rm ~/.cache -rf

# entry point
VOLUME $db_dir
ENV DB_DIRECTORY=$db_dir

COPY ./scripts/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
