from __future__ import annotations
from abc import ABC, abstractmethod
from attrs import define, field
import math
import os
import threading
import s3transfer as s3t
from pgraws import pgraws
from datetime import datetime
from dateutil import tz
from typing import Any, Optional, Dict
from mlcore_utils.model.common import Secret_Getter, MLCore_Secret
from result import Result, Err, Ok, is_err, is_ok
import json
import boto3
from boto3.session import Session

from mlcore_utils.model.file import Generator_To_FileLike

AWS_CONSTANTS = {
    "prod": {
        "ecr_account": "867531445002",
        "aws_account_num": "970362792838",
        "aws_role_arn": "k8s-sa-mlcore-tgw-kaniko_build",
        "aws_account_name": "aws0gd",
    },
    "dev": {
        "ecr_account": "867531445002",
        "aws_account_num": "004782836026",
        "aws_role_arn": "k8s-sa-mlcore-tgw-kaniko_build",
        "aws_account_name": "aws0gp",
    },
}


class AWS_Credentials(ABC):
    def __init__(self, logger, region: str = "us-east-1") -> None:
        self.region = region
        self._session: Optional[Session] = None
        self.logger = logger

    @abstractmethod
    def _get_sess(self) -> Session:
        pass

    def get_aws_session(self) -> Result[Session, str]:
        if self._session:
            return Ok(self._session)
        else:
            try:
                self._session = self._get_sess()
                return Ok(self._session)
            except Exception as e:
                return Err(str(e))


class AWS_Default_Credentials(AWS_Credentials):
    def __init__(self, logger, region: str = "us-east-1") -> None:
        super().__init__(logger, region)

    def _get_sess(self) -> Session:
        return boto3.Session(region_name=self.region)


class AWS_STS_Credentials(AWS_Credentials):
    def __init__(
        self,
        aws_access_key_id,
        aws_secret_access_key,
        aws_session_token,
        logger,
        region: str = "us-east-1",
    ) -> None:
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.aws_session_token = aws_session_token
        super().__init__(logger, region)

    def _get_sess(self) -> Session:
        return boto3.Session(
            region_name=self.region,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token,
        )


class PGR_STS_Credentials(AWS_Credentials):
    def __init__(
        self,
        aws_account,
        role,
        username,
        password: MLCore_Secret,
        duration=900,
        logger=None,
        region: str = "us-east-1",
    ) -> None:
        self.aws_account = aws_account
        self.role = role
        self.username = username
        self.password = password
        self._credentials: Dict[str, Any] = {}
        self._duration = duration
        self._role = {
            "ldap": self.role,
            "alias": self.role,
            "account": self.aws_account,
            "principal": f"arn:aws:iam::{self.aws_account}:saml-provider/PGRSTS",
            "role": f"arn:aws:iam::{self.aws_account}:role/{self.role}",
        }
        super().__init__(logger, region)

    def should_get_credentials(self):
        condition_to_get_creds_1 = not self._session
        condition_to_get_creds_2 = not self._credentials
        condition_to_get_creds_3 = (
            self._credentials
            and (self._credentials["Expiration"] - datetime.now(tz.UTC)).seconds < 120
        )
        return (
            condition_to_get_creds_1
            or condition_to_get_creds_2
            or condition_to_get_creds_3
        )

    def get_creds_from_pgraws(self) -> Dict[str, Any]:
        saml_assertion = pgraws.get_aws_saml_assertion(
            use_sa_creds=False,
            username=self.username,
            password=self.password.get_secret_value(),
        )
        return pgraws.get_credentials(self._role, saml_assertion)

    def _assign_creds(self):
        self._credentials = self.get_creds_from_pgraws()

    def get_credentials(self):
        if self.should_get_credentials():
            self._assign_creds()
        return self._credentials

    def _get_sess(self, region="us-east-1") -> Session:
        sts_credentials_session_provider = AWS_STS_Credentials(
            aws_access_key_id=self._credentials["AccessKeyId"],
            aws_secret_access_key=self._credentials["SecretAccessKey"],
            aws_session_token=self._credentials["SessionToken"],
            logger=self.logger,
        )
        return sts_credentials_session_provider._get_sess()

    def get_aws_session(self) -> Result[Session, str]:
        try:
            if self.should_get_credentials():
                self._assign_creds()
                self._session = self._get_sess()
                return Ok(self._session)
            else:
                return super().get_aws_session()
        except Exception as e:
            return Err(str(e))


class AWS_Utils(object):
    def __init__(self, aws_credentials: AWS_Credentials, service: str, logger) -> None:
        self.aws_credentials = aws_credentials
        self.service = service
        self.logger = logger

    def get_client(self):
        session_res = self.aws_credentials.get_aws_session()
        if is_ok(session_res):
            return session_res.ok_value.client(self.service)
        elif is_err(session_res):
            raise Exception(session_res.err_value)
        else:
            raise Exception("Creating Boto3 Client failed with unknown error")

class AWS_System_Manager(AWS_Utils):
    def __init__(self, aws_credentials: AWS_Credentials, logger) -> None:
        super().__init__(aws_credentials, "ssm", logger)

    def get_parameter_value(self, parameter_name) -> Result[Any, err]:
        try:
            param_val = self.get_client().get_parameter(Name=parameter_name)["Parameter"]["Value"]
            return Ok(param_val)
        except Exception as e:
            return Err(f"Error while getting value for parameter {parameter_name} : {str(e)}")



class AWS_SecretsManager_Secret_Getter(Secret_Getter):
    def __init__(
        self, credentials: AWS_Credentials, secret_name: str, secret_key: str, logger
    ):
        self.credentials = credentials
        self.logger = logger
        self.secret_name = secret_name
        self.secret_key = secret_key

    def get_secret(self) -> Result[MLCore_Secret, str]:
        ssm_client = AWS_Utils(self.credentials, "secretsmanager", self.logger).get_client()
        try:
            jetstream_secret = ssm_client.get_secret_value(SecretId=self.secret_name)[
                "SecretString"
            ]
            return Ok(MLCore_Secret(json.loads(jetstream_secret)[self.secret_key]))
        except Exception as e:
            return Err("Error Getting Secret from AWS Secrets Manager. " + str(e))


class AWS_S3_Util(AWS_Utils):
    def __init__(self, aws_credentials: AWS_Credentials, logger) -> None:
        super().__init__(aws_credentials, "s3", logger)

    def _object_key_validator(self, bucket: str, key: str):
        if bucket.startswith("s3:"):
            # raise Exception('Please provide bucket without s3 protocol')
            without_protocol = bucket.replace("s3://", "")
            return (
                (
                    without_protocol[:-1]
                    if without_protocol.endswith("/")
                    else without_protocol
                ),
                key[:-1] if key.endswith("/") else key,
            )
        else:
            return (
                bucket[:-1] if bucket.endswith("/") else bucket,
                key[:-1] if key.endswith("/") else key,
            )

    def upload_generator_to_s3(self, *, generator, bucket: str, key: str):
        stream = Generator_To_FileLike(generator)
        self.upload_stream(stream=stream, bucket=bucket, key=key)

    def upload_stream(
        self, *, stream, bucket: str, key: str
    ):  # force parameter names to be specified in the call.
        target_bucket, target_key = self._object_key_validator(bucket, key)
        self.logger.debug("Upload To: " + "s3://" + target_bucket + "/" + target_key)
        self.get_client().upload_fileobj(stream, target_bucket, target_key)

    def upload_stream_with_progress(
        self, *, stream, bucket: str, key: str, progress_cls
    ):
        target_bucket, target_key = self._object_key_validator(bucket, key)
        self.logger.debug("Upload To: " + "s3://" + target_bucket + "/" + target_key)
        self.get_client().upload_fileobj(
            stream, target_bucket, target_key, Callback=progress_cls
        )

    def upload_file(
        self,
        *,
        filename: str,
        bucket: str,
        key: str,
        chunk_size: int = 400000000,
        max_concurrency: int = 10,
    ):  # force parameter names to be specified in the call.
        target_bucket, target_key = self._object_key_validator(bucket, key)
        self.logger.debug(
            "Upload Start  : "
            + filename
            + " ; To: "
            + "s3://"
            + target_bucket
            + "/"
            + target_key
        )
        tc = s3t.TransferConfig(
            multipart_threshold=chunk_size,
            max_concurrency=max_concurrency,
            num_download_attempts=10,
        )
        t = s3t.S3Transfer(self.get_client(), config=tc)
        try:
            t.upload_file(
                filename,
                target_bucket,
                target_key,
                callback=ProgressPercentage(
                    filename, self.logger, filename + " Upload"
                ),
            )
            self.logger.debug(
                "Upload Finish : "
                + filename
                + " ; To: "
                + "s3://"
                + target_bucket
                + "/"
                + target_key
            )
        except Exception as e:
            self.logger.error("Upload Failed : " + filename + " ; Error: " + str(e))
            raise e


class ProgressPercentage(object):
    def __init__(self, filename, logger, tag=None, size=None):
        self._size = size if size != None else float(os.path.getsize(filename))
        self._tag = "s3-operation for " + filename if tag == None else tag
        self._seen_so_far = 0
        self._lock = threading.Lock()
        self._previous_seen = 0
        self._current_seen = 0
        self._logger = logger

    def __call__(self, bytes_amount):
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = (self._seen_so_far / self._size) * 100
            if math.floor(percentage) % 5 == 0:
                self._current_seen = math.floor(percentage)
                if self._current_seen != self._previous_seen:
                    self._previous_seen = self._current_seen
                    self._logger.debug(self._tag + " Progress: " + str(percentage))


@define
class AWS_Accounts_For_Blacklodge(object):
    ecr_account: str = field()
    aws_account_num: str = field()
    aws_role_arn: str = field()
    aws_account_name: str = field()

    @classmethod
    def create_from_env(cls, env: str) -> AWS_Accounts_For_Blacklodge:
        return AWS_Accounts_For_Blacklodge(
            ecr_account=AWS_CONSTANTS[env]["ecr_account"],
            aws_account_num=AWS_CONSTANTS[env]["aws_account_num"],
            aws_role_arn=AWS_CONSTANTS[env]["aws_role_arn"],
            aws_account_name=AWS_CONSTANTS[env]["aws_account_name"],
        )

    def get_ecr_image_path(
        self, namespace, environment, container_path, container_version
    ):
        return f"{self.ecr_account}.dkr.ecr.us-east-1.amazonaws.com/internal/containerimages/eds/{namespace}/{environment}/{container_path}/{container_version}"
