from __future__ import annotations
import requests
import boto3
from result import Err, Ok, Result
import toml
from dockerfile_parse import DockerfileParser
from typing import Optional, Any, List
from enum import Enum
from attrs import define, field

from mlcore_utils.model.aws import AWS_Accounts_For_Blacklodge, AWS_Utils
from mlcore_utils.model.gh import GitHub_Repo, GitHub_Auth


class Prebuilt_Container(str, Enum):
    BASE = "base"
    LIGHT_GBM = "light_gbm"
    KAFKA = "kafka"
    BATCH = "batch"
    H2O = "h2o"
    H2O_BATCH = "h2o_batch"

    def get_prebuilt_container(self, python_version: str = "3.9"):
        version_adder = lambda x: "" if x == "3.8" else "_" + x.replace(".", "_")
        if self == Prebuilt_Container.H2O_BATCH:
            return "h2o_batch_container"
        if self == Prebuilt_Container.H2O:
            return "h2o_container"
        if self == Prebuilt_Container.BATCH:
            return "batch_container"
        if self == Prebuilt_Container.KAFKA:
            return "kafka_container"
        else:
            return self.value + "_container" + version_adder(python_version)


@define
class Blacklodge_Container(object):
    git_repo_address: str = field()
    github_auth: GitHub_Auth = field()
    dockerfile_path: str = field()
    prebuilt_container: Prebuilt_Container = field()
    context_path: str = field(default="./src")
    github_repo: GitHub_Repo = field(init=False)

    def __attrs_post_init__(self):
        self.github_repo = GitHub_Repo.get_from_inputs(
            git_repo_url=self.git_repo_address, github_auth=self.github_auth
        )

    def initialize_github_repo(self, github_auth: GitHub_Auth):
        self.github_repo = GitHub_Repo.get_from_inputs(
            git_repo_url=self.git_repo_address, github_auth=self.github_auth
        )

    @classmethod
    def get_from_inputs(
        cls,
        git_repo_address: str,
        github_auth: GitHub_Auth,
        docker_file_path: str,
        prebuilt_container: Prebuilt_Container,
        context_path: str = "./src",
    ) -> Blacklodge_Container:
        return Blacklodge_Container(
            git_repo_address,
            github_auth,
            docker_file_path,
            prebuilt_container,
            context_path,
        )

    def get_container_build_args(self):
        pass

    def get_container_env_vars(self):
        pass

    def parse_docker_file(self) -> Optional[DockerfileParser]:
        pass

    @classmethod
    def get_from_prebuilt_container(
        cls, prebuilt_container: Prebuilt_Container, github_auth: GitHub_Auth
    ) -> Optional[Blacklodge_Container]:
        if prebuilt_container == Prebuilt_Container.BASE:
            return Blacklodge_Container(
                git_repo_address="https://github.com/PCDST/blacklodge_containers/tree/simple",
                github_auth=github_auth,
                dockerfile_path="dockerfiles/base_container/Dockerfile",
                prebuilt_container=prebuilt_container,
                context_path="./src",
            )


@define
class Pipeline_Runtime_Config:
    blacklodge_container: Blacklodge_Container = field()
    minimum_replicas: Optional[int] = field(default=None)
    maximum_replicas: Optional[int] = field(default=None)
    target_cpu_utilization: Optional[int] = field(default=None)
    target_memory_utilization: Optional[int] = field(default=None)
    memory: Optional[int] = field(default=None)
    min_cpu: Optional[float] = field(default=0.5)
    max_cpu: Optional[float] = field(default=1.5)
    min_memory_mb: Optional[int] = field(default=750)
    max_memory_mb: Optional[int] = field(default=1500)
    replicas: Optional[int] = field(default=None)
    inputs: Optional[Any] = field(default=None)
    otel_tracing: bool = field(default=False)

    def __attrs_post_init__(self):
        if self.replicas and self.minimum_replicas:
            raise ValueError(
                "Either provide runtime.autoscale or runtime.fixed_scale; but not both"
            )
        if not self.replicas:
            if (
                self.minimum_replicas
                and self.maximum_replicas
                and self.target_cpu_utilization
                and self.target_memory_utilization
                and self.min_cpu
                and self.max_cpu
                and self.min_memory_mb
                and self.max_memory_mb
            ):
                # if self.cpu < 0.5 or self.cpu > 8.0:
                #    raise ValueError("cpu value should be between 0.5 and 8.0")
                if self.target_cpu_utilization < 40 or self.target_cpu_utilization > 90:
                    raise ValueError(
                        "target_cpu_utilization value should be between 40 and 90"
                    )
                # if self.memory < 1 or self.memory > 60:
                #    raise ValueError("memory value should be between 1 and 60")
                if not (self.minimum_replicas > 0):
                    raise ValueError("min_replicas should be more than 0")
                if not (self.maximum_replicas <= 32):
                    raise ValueError("max_replicas should be less than or equal to 32")
                if (
                    self.minimum_replicas
                    and self.maximum_replicas
                    and self.minimum_replicas >= self.maximum_replicas
                ):
                    raise ValueError(
                        "Minimum Replicas should be less than maximum replicas"
                    )
                pass
            else:
                raise ValueError(
                    "Please provide complete runtime.autoscale if you are not providing runtime.fixed_scale"
                )

    @staticmethod
    def get_from_inputs(
        blacklodge_container,
        minimum_replicas,
        maximum_replicas,
        target_cpu_utilization,
        target_memory_utilization,
        min_cpu,
        max_cpu,
        min_memory_mb,
        max_memory_mb,
        replicas,
        inputs,
    ):
        p = Pipeline_Runtime_Config(
            blacklodge_container=blacklodge_container,
            minimum_replicas=minimum_replicas,
            maximum_replicas=maximum_replicas,
            target_cpu_utilization=target_cpu_utilization,
            target_memory_utilization=target_memory_utilization,
            min_cpu=min_cpu,
            max_cpu=max_cpu,
            min_memory_mb=min_memory_mb,
            max_memory_mb=max_memory_mb,
            replicas=replicas,
            inputs=inputs,
        )
        return p


class Blacklodge_Model_Type(str, Enum):
    MODEL = "model"
    PIPELINE = "pipeline"
    JOB = "job"
    CRONJOB = "cronjob"


@define
class Pipeline_Alias:
    version: int = field()
    alias: str = field()


class Environment(str, Enum):
    PRODUCTION = "production"
    QA_ACCEPTANCE = "qa_acceptance"
    TEST = "test"
    TRAINING = "training"
    STRESS = "stress"
    DEVELOPMENT = "development"


@define
class Blacklodge_Model:
    name: str = field()
    version: int = field()
    python_version: str = field()
    git_repo_url: str = field()
    git_repo_branch: str = field()
    runtime_config: Pipeline_Runtime_Config = field()
    environment: Environment = field()
    service_account: str = field()
    cron_schedule: str = field(default="*")
    object_type: Blacklodge_Model_Type = field(default=Blacklodge_Model_Type.PIPELINE)
    git_repo_path: Optional[str] = field(default=None)
    git_repo: Optional[GitHub_Repo] = field(default=None)
    blacklodge_helm_charts_git_repo: Optional[GitHub_Repo] = field(default=None)
    aliases: List[Pipeline_Alias] = field(factory=list)
    user_email: List[str] = field(
        default=["sam_s_kolli@progressive.com"]
    )  # TODO: Fix this

    def __attrs_post_init__(self):
        pass

    def get_container_image_name(self):
        return f"blacklodge-{self.object_type.value}-{self.name}"

    def get_container_tag(self):
        return f"{self.version}"

    def get_ecr_image_path(
        self,
        aws_accounts_for_blacklodge: AWS_Accounts_For_Blacklodge,
        platform: str,
        namespace: str,
    ):
        return f"{aws_accounts_for_blacklodge.ecr_account}.dkr.ecr.us-east-1.amazonaws.com/internal/containerimages/{platform}/{namespace}/blacklodge-{self.object_type.value}-{self.name}:{self.version}"

    def initialize_github_repo(self, github_auth: GitHub_Auth):
        self.git_repo = GitHub_Repo.get_from_inputs(
            git_repo_url=self.git_repo_url,
            git_repo_branch=self.git_repo_branch,
            git_repo_path=self.git_repo_path,
            github_auth=github_auth,
        )

    @name.validator
    def validate_name(self, attribute, value):
        if "_" in value:
            raise ValueError("Model/Pipline/Job name cannot contain underscores.")

    @staticmethod
    def from_dict(data, helmcharts_repo: GitHub_Repo, github_auth: GitHub_Auth):
        name = data["model"]["name"]
        version = data["model"]["version"]

        git_repo_url = data["model"]["git_repo_url"]
        git_repo_branch = (
            data["model"]["git_repo_branch"]
            if "git_repo_branch" in data["model"]
            else None
        )
        git_repo_path = (
            data["model"]["git_repo_path"] if "git_repo_path" in data["model"] else None
        )
        repo = GitHub_Repo.get_from_inputs(
            git_repo_url=git_repo_url,
            git_repo_branch=git_repo_branch,
            git_repo_path=git_repo_path,
            github_auth=github_auth,
        )
        aliases = [
            Pipeline_Alias(entry["version_number"], entry["alias_name"])
            for entry in data["alias"]
        ]

        prebuilt_container = Prebuilt_Container(data["runtime"]["container"])
        blacklodge_container = Blacklodge_Container.get_from_prebuilt_container(
            prebuilt_container, github_auth
        )

        replicas = (
            data["runtime"]["fixed_scale"]["replicas"]
            if "fixed_scale" in data["runtime"]
            and "replicas" in data["runtime"]["fixed_scale"]
            else None
        )
        minimum_replicas = (
            data["runtime"]["autoscale"]["minimum_replicas"]
            if "autoscale" in data["runtime"]
            else None
        )
        maximum_replicas = (
            data["runtime"]["autoscale"]["maximum_replicas"]
            if "autoscale" in data["runtime"]
            else None
        )
        target_cpu_utilization = (
            data["runtime"]["autoscale"]["target_cpu_utilization"]
            if "autoscale" in data["runtime"]
            else None
        )
        target_memory_utilization = (
            data["runtime"]["autoscale"]["target_memory_utilization"]
            if "autoscale" in data["runtime"]
            else None
        )
        min_cpu = (
            data["runtime"]["autoscale"]["min_cpu"]
            if "autoscale" in data["runtime"]
            else None
        )
        max_cpu = (
            data["runtime"]["autoscale"]["max_cpu"]
            if "autoscale" in data["runtime"]
            else None
        )
        min_memory_mb = (
            data["runtime"]["autoscale"]["min_memory_mb"]
            if "autoscale" in data["runtime"]
            else None
        )
        max_memory_mb = (
            data["runtime"]["autoscale"]["max_memory_mb"]
            if "autoscale" in data["runtime"]
            else None
        )
        inputs = (
            data["runtime"]["additional_data"]["data"]
            if "additional_data" in data["runtime"]
            and "data" in data["runtime"]["additional_data"]
            else None
        )

        runtime_config = Pipeline_Runtime_Config.get_from_inputs(
            blacklodge_container,
            minimum_replicas,
            maximum_replicas,
            target_cpu_utilization,
            target_memory_utilization,
            min_cpu,
            max_cpu,
            min_memory_mb,
            max_memory_mb,
            replicas,
            inputs,
        )

        service_account = "tbd"  # data['model']['service_account'],
        environment = (
            Environment.DEVELOPMENT
        )  # Environment(data['model']["environment"]),

        model = Blacklodge_Model(
            name=name,
            version=version,
            python_version="3.9",
            git_repo_url=git_repo_url,
            git_repo_branch=git_repo_branch,
            git_repo_path=git_repo_path,
            git_repo=repo,
            aliases=aliases,
            runtime_config=runtime_config,
            service_account=service_account,
            environment=environment,
            blacklodge_helm_charts_git_repo=helmcharts_repo,
        )
        return model

    @staticmethod
    def from_toml_file(
        file_path: str, helmcharts_repo: GitHub_Repo, github_auth: GitHub_Auth
    ):
        with open(file_path) as f:
            data = toml.load(f)
        model = Blacklodge_Model.from_dict(data, helmcharts_repo, github_auth)
        return model


@define
class Blacklodge_BusinessUnit(object):
    custom_groups: List[str] = field(factory=list)

    def get_namespace(self) -> str:
        return "mlcore"

    def get_teamname(self) -> str:
        return "mlcore"


@define
class Blacklodge_User(object):
    lan_id: str = field()
    name: str = field()
    email: str = field()
    username: str = field()
    business_unit: Blacklodge_BusinessUnit = field()

    @classmethod
    def create_from_cognito_saml_token(
        cls, user_pool_id: str, aws_util_for_cognito: AWS_Utils, saml_token: str
    ) -> Blacklodge_User:
        cognito_client = aws_util_for_cognito.get_client()
        try:
            user_pool_details = cognito_client.describe_user_pool(
                UserPoolId=user_pool_id
            )["UserPool"]
            region = aws_util_for_cognito.aws_credentials.region
            user_info_endpoint = f"https://{user_pool_details['Domain']}.auth.{region}.amazoncognito.com/oauth2/userInfo"
            user_info_auth_header = {"Authorization": f"Bearer {saml_token}"}

            r = requests.post(
                user_info_endpoint, headers=user_info_auth_header, timeout=2
            )
            data = r.json()
            return Blacklodge_User(
                lan_id=data["custom:lan_id"],
                name=data["name"],
                email=data["email"],
                business_unit=Blacklodge_BusinessUnit(
                    custom_groups=data["custom:groups"]
                ),
                username=data["username"],
            )
        except Exception as e:
            raise e

    @classmethod
    def create_from_cognito_saml_token_v2(
        cls, user_pool_id: str, aws_util_for_cognito: AWS_Utils, saml_token: str
    ) -> Result[Blacklodge_User, str]:
        cognito_client = aws_util_for_cognito.get_client()
        try:
            user_pool_details = cognito_client.describe_user_pool(
                UserPoolId=user_pool_id
            )["UserPool"]
        except Exception as e:
            return Err(f"Error describing Cognito User Pool {user_pool_id}: {str(e)}")

        try:
            region = aws_util_for_cognito.aws_credentials.region
            user_info_endpoint = f"https://{user_pool_details['Domain']}.auth.{region}.amazoncognito.com/oauth2/userInfo"
            user_info_auth_header = {"Authorization": f"Bearer {saml_token}"}

            r = requests.post(
                user_info_endpoint, headers=user_info_auth_header, timeout=2
            )
            data = r.json()
        except Exception as e:
            return Err(
                f"Error getting userinfo from cognito {user_info_endpoint}: {str(e)}"
            )

        if "name" in data:
            return Ok(
                Blacklodge_User(
                    lan_id=data["custom:lan_id"],
                    name=data["name"],
                    email=data["email"],
                    business_unit=Blacklodge_BusinessUnit(
                        custom_groups=data["custom:groups"]
                    ),
                    username=data["username"],
                )
            )
        else:
            return Err(
                f"Got response from Cognito UserEndpoint but there is an error: {data}"
            )

    def get_namespace(self) -> str:
        return self.business_unit.get_namespace()

    def get_teamname(self) -> str:
        return self.business_unit.get_teamname()
