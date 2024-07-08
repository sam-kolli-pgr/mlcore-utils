################################################
# Initialize userfiles in init container  #
################################################
ARG PYTHON_VERSION

FROM ccir.prci.com/base_docker.io/python:${PYTHON_VERSION}-slim-buster AS s3_getter

ENV AWS_DEFAULT_REGION='us-east-1'

ENV HTTPS_PROXY=http://servercache.prci.com:55000
ENV https_proxy=$HTTPS_PROXY
ENV NO_PROXY=.prci.com,.prog1.com,.pgrcloud.app,.progcloud.com,.progcloudq.com,ec2.internal,localhost,172.17.0.1,127.0.0.1,169.254.169.254,10.*.*.*
ENV no_proxy=$NO_PROXY
ENV HTTP_PROXY=http://servercache.prci.com:55000
ENV http_proxy=$HTTP_PROXY
ENV AWS_STS_REGIONAL_ENDPOINTS=regional

COPY dockerfiles/create_auth_conf.sh .
RUN chmod 755 create_auth_conf.sh

RUN  --mount=type=secret,id=ARTIFACTORY_BUILDUSER --mount=type=secret,id=ARTIFACTORY_BUILDUSER_PASSWORD \
    export ARTIFACTORY_BUILDUSER=$(cat /run/secrets/ARTIFACTORY_BUILDUSER) \
    && export ARTIFACTORY_BUILDUSER_PASSWORD=$(cat /run/secrets/ARTIFACTORY_BUILDUSER_PASSWORD) && \
    ./create_auth_conf.sh && apt-get update -y && \
    apt-get install -y ca-certificates curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install boto3==1.28.47 --index https://$ARTIFACTORY_BUILDUSER:$ARTIFACTORY_BUILDUSER_PASSWORD@progressive.jfrog.io/progressive/api/pypi/pgr-pypi/simple

RUN curl -L -o /root/PGR.crt http://crl3.prci.com/Progressive%20PKI%20G3.ca-bundle.crt

RUN cp /root/PGR.crt /etc/ssl/certs/
RUN cat /root/PGR.crt >> /etc/ssl/certs/ca-certificates.crt

ENV AWS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

ARG PIPELINE_NAME
ARG PIPELINE_VERSION
ARG APP_TYPE
ARG AWS_ACCOUNT_NUM

ENV FOLDER_NAME=$APP_TYPE
ENV FILENAME="$APP_TYPE.tar.gz"

WORKDIR /s3
COPY ./container ./

#Download the pipeline_registry code from S3, create dir named "pipeline" and untar file into pipeline folder
# When manually testing, add `--strip-components 1` to the tar line
RUN --mount=type=secret,id=ASSUMED_AWS_ACCESS_KEY_ID --mount=type=secret,id=ASSUMED_AWS_SECRET_ACCESS_KEY --mount=type=secret,id=ASSUMED_AWS_SESSION_TOKEN \
    export ASSUMED_AWS_ACCESS_KEY_ID=$(cat /run/secrets/ASSUMED_AWS_ACCESS_KEY_ID) \
    && export ASSUMED_AWS_SECRET_ACCESS_KEY=$(cat /run/secrets/ASSUMED_AWS_SECRET_ACCESS_KEY) \
    && export ASSUMED_AWS_SESSION_TOKEN=$(cat /run/secrets/ASSUMED_AWS_SESSION_TOKEN) && \
    python3 /s3/get_s3.py $AWS_ACCOUNT_NUM $PIPELINE_NAME $PIPELINE_VERSION $APP_TYPE $FILENAME && \
    mkdir $FOLDER_NAME && \
    tar xf $FILENAME -C $FOLDER_NAME && \
    rm $FILENAME


RUN useradd pgruser

################################################
# End common container initialization          #
################################################

################################################
# Initialize pipeline runtime                   #
################################################

ARG PYTHON_VERSION

FROM ccir.prci.com/base_docker.io/python:${PYTHON_VERSION}-slim-buster

EXPOSE 8081


ARG PIPELINE_NAME
ARG PIPELINE_VERSION
ARG APP_TYPE
ARG AWS_ACCOUNT_NUM
ARG LINUX_TEMPLATE

ENV AWS_ACCOUNT_NUM=${AWS_ACCOUNT_NUM}
ENV PIPELINE_NAME=${PIPELINE_NAME}
ENV PIPELINE_VERSION=${PIPELINE_VERSION}
ENV APP_TYPE=${APP_TYPE}
ENV LINUX_TEMPLATE=${LINUX_TEMPLATE}

ENV AWS_STS_REGIONAL_ENDPOINTS=regional
ENV AWS_REGION="us-east-1"

COPY dockerfiles/create_auth_conf.sh .
RUN chmod 755 create_auth_conf.sh

# Set some environment variables. PYTHONUNBUFFERED keeps Python from buffering
#  our standard output stream, which means that logs can be delivered to the
# user quickly. PYTHONDONTWRITEBYTECODE keeps Python from writing the .pyc
# files which are unnecessary in this case.
ENV PYTHONUNBUFFERED=TRUE
ENV PYTHONDONTWRITEBYTECODE=TRUE

WORKDIR /opt/app

# ref https://pipenv.pypa.io/en/latest/install/#isolated-installation-of-pipenv-with-pipx
ENV PIPX_BIN_DIR="/usr/local/bin"
RUN  --mount=type=secret,id=ARTIFACTORY_BUILDUSER --mount=type=secret,id=ARTIFACTORY_BUILDUSER_PASSWORD \
    export ARTIFACTORY_BUILDUSER=$(cat /run/secrets/ARTIFACTORY_BUILDUSER) \
    && export ARTIFACTORY_BUILDUSER_PASSWORD=$(cat /run/secrets/ARTIFACTORY_BUILDUSER_PASSWORD) && \
    apt-get update -y && apt-get install -y ca-certificates curl && \
    python3 -m pip install pipenv --index https://$ARTIFACTORY_BUILDUSER:$ARTIFACTORY_BUILDUSER_PASSWORD@progressive.jfrog.io/progressive/api/pypi/pgr-pypi/simple

COPY ./container ./

## Linux package templates for customer ease of use
COPY ./linux_templates ./

## Install packages from given template if LINUX_TEMPLATE variable is provided
RUN if [ -n "${LINUX_TEMPLATE}" ]; then \
    xargs apt-get install -y < /opt/app/$LINUX_TEMPLATE/linux_packages.txt; \
fi

COPY --from=s3_getter /s3/$APP_TYPE ./$APP_TYPE/

### Install custom linux packages
ENV LINUX_PACKAGES=/opt/app/$APP_TYPE/linux_packages.txt
RUN if [ -f $LINUX_PACKAGES ]; then \
    xargs apt-get install -y < $LINUX_PACKAGES; \
fi

### Setup groups and access
RUN chmod 755 /usr/local/bin/pipenv
RUN chmod 733 /var/log/

RUN useradd -m pgruser

RUN chown -R pgruser:pgruser /opt/app/

RUN ln -s /pgr/stratos-pgr-ca.pem /etc/ssl/certs/PGR.crt

USER pgruser

ENV PATH="${PATH}:/home/pgruser/.local/bin/"

ENV PIPENV_PIPFILE=/opt/app/$APP_TYPE/Pipfile
RUN  --mount=type=secret,id=ARTIFACTORY_BUILDUSER,uid=1000 --mount=type=secret,id=ARTIFACTORY_BUILDUSER_PASSWORD,uid=1000 \
    export ATF_USERNAME=$(cat /run/secrets/ARTIFACTORY_BUILDUSER) && \
    export ATF_TOKEN=$(cat /run/secrets/ARTIFACTORY_BUILDUSER_PASSWORD) && \
    pipenv install --verbose --deploy --system --index https://$ATF_USERNAME:$ATF_TOKEN@progressive.jfrog.io/progressive/api/pypi/pgr-pypi/simple


CMD ["pipenv", "run", "bash", "run.sh"]
