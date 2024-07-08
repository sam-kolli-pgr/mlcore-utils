from __future__ import annotations
from abc import ABC, abstractmethod
import base64
from enum import Enum
import hashlib
import yaml
import json
from result import Err, Ok, Result, is_ok, is_err
import time
import ast
import requests
from typing import List, Optional, Tuple, Any, Dict, TypedDict
from attrs import define, field, asdict

from mlcore_utils.model.aws import AWS_Accounts_For_Blacklodge
from mlcore_utils.model.common import (
    Http_Method,
    Runtime_Environment,
    Runtime_Environment_Detector,
    Secret_Getter,
    Blacklodge_Action_Status,
)
from mlcore_utils.model.blacklodge import (
    Blacklodge_Model,
    Blacklodge_BusinessUnit,
    Blacklodge_Model_Type,
    Blacklodge_User,
    Pipeline_Alias,
)
from mlcore_utils.model.stratos_interface import (
    Stratos_AppOwnersMetadata_V1,
    Stratos_AppSyncArgoRequest_V1,
    Stratos_ContainerBuild_Metadata_V1,
    Stratos_ContainerHelDeployRequest_V1,
    Stratos_NamespaceMetadata_V1,
    Stratos_ProjectMetadata_V1,
)

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


class Stratos_Environment(str, Enum):
    PROD = "prod"
    NONPROD = "nonprod"

    def detect_from_runtime_environment(self):
        runtime_env = Runtime_Environment_Detector.detect()
        if (
            runtime_env == Runtime_Environment.CLOUD9
            or runtime_env == Runtime_Environment.LOCAL_DOCKER
            or runtime_env == Runtime_Environment.LOCAL_MAC
        ):
            return Stratos_Environment.NONPROD
        elif runtime_env == Runtime_Environment.STRATOS:
            return Stratos_Environment.PROD


class Blacklodge_Helm_Chart_Type(str, Enum):
    NAMESPACE = "blacklodge-namespace-resources"
    ALIAS = "blacklodge-user-alias"
    CRONJOB = "blacklodge-user-cronjob"
    JOB = "blacklodge-user-job"
    PIPELINE = "blacklodge-user-pipeline"


@define
class Splunk_Constants(object):
    environment: str = field(default="Development")


@define
class AWS_Accounts_For_Blacklodge(object):
    ecr_account: str = field()
    aws_account_num: str = field()
    aws_role_arn: str = field()
    aws_account_name: str = field()
    aws_region: str = field(default="us-east-1")

    @classmethod
    def create_from_env(cls, env: str) -> AWS_Accounts_For_Blacklodge:
        return AWS_Accounts_For_Blacklodge(
            ecr_account=AWS_CONSTANTS[env]["ecr_account"],
            aws_account_num=AWS_CONSTANTS[env]["aws_account_num"],
            aws_role_arn=AWS_CONSTANTS[env]["aws_role_arn"],
            aws_account_name=AWS_CONSTANTS[env]["aws_account_name"],
        )

    @classmethod
    def create_from_runtime_environment(cls) -> AWS_Accounts_For_Blacklodge:
        runtime_env = Runtime_Environment_Detector.detect()
        if (
            runtime_env == Runtime_Environment.LOCAL_DOCKER
            or runtime_env == Runtime_Environment.LOCAL_MAC
            or runtime_env == Runtime_Environment.CLOUD9
        ):
            env = "dev"
        elif runtime_env == Runtime_Environment.STRATOS:
            env = "prod"
        else:
            raise Exception(
                "Cannot create AWS_Accounts_For_Blacklodge from given runtime env "
                + runtime_env
            )
        return AWS_Accounts_For_Blacklodge(
            ecr_account=AWS_CONSTANTS[env]["ecr_account"],
            aws_account_num=AWS_CONSTANTS[env]["aws_account_num"],
            aws_role_arn=AWS_CONSTANTS[env]["aws_role_arn"],
            aws_account_name=AWS_CONSTANTS[env]["aws_account_name"],
        )


@define
class Stratos_Application_Values(object):
    platform: str = field(default="eds")
    account_id: str = field(default="1111111")
    allowed_cluster_types: List[str] = field(default=["blacklodge"])
    helm_aws_account_num: str = field(default="867531445002")
    helm_aws_region: str = field(default="us-east-1")
    environment: Stratos_Environment = field(default=Stratos_Environment.NONPROD)
    helm_repositry: str = field(init=False)

    def __attrs_post_init__(self):
        self.helm_repositry = f"oci://{self.helm_aws_account_num}.dkr.ecr.{self.helm_aws_region}.amazonaws.com/internal/helm/eds/blacklodge"

    def get_project_identifier(self, blacklodge_user: Blacklodge_User):
        return blacklodge_user.get_teamname()

    def get_platform(self):
        return self.platform

    def get_environment(self):
        return self.environment


@define
class HelmChart_Version_Getter(ABC):
    versions: Optional[Dict[Blacklodge_Helm_Chart_Type, str]] = field(default=None)

    @abstractmethod
    def assign_versions(self) -> Result[Dict[Blacklodge_Helm_Chart_Type, str], str]:
        pass

    def get_chart_versions(self) -> Result[Dict[Blacklodge_Helm_Chart_Type, str], str]:
        if not self.versions:
            assign_result = self.assign_versions()
            if is_ok(assign_result):
                self.versions = assign_result.ok_value
            elif is_err(assign_result):
                print(
                    "Getting Helm Chart Versions failed with error "
                    + assign_result.err_value
                )
            else:
                print("Getting Helm Chart Versions failed with unknown error")

        return Ok(self.versions)


@define
class HelmChart_Version_Hardcoded_Getter(HelmChart_Version_Getter):
    versions: Optional[Dict[Blacklodge_Helm_Chart_Type, str]] = field(default=None)

    def assign_versions(self) -> Result[Dict[Blacklodge_Helm_Chart_Type, str], str]:
        return Ok(
            {
                Blacklodge_Helm_Chart_Type.PIPELINE: "0.3.25",
                Blacklodge_Helm_Chart_Type.ALIAS: "0.2.8",
                Blacklodge_Helm_Chart_Type.CRONJOB: "0.2.3",
                Blacklodge_Helm_Chart_Type.JOB: "0.2.4",
                Blacklodge_Helm_Chart_Type.NAMESPACE: "0.1.1",
            }
        )


@define
class HelmChart_Version_From_GitHub_Getter(HelmChart_Version_Getter):
    versions: Optional[Dict[Blacklodge_Helm_Chart_Type, str]] = field(default=None)

    def assign_versions(self) -> Result[Dict[Blacklodge_Helm_Chart_Type, str], str]:
        raise NotImplementedError(
            "Getting ChartVersions by Talking to GitHUb is not implemented yet"
        )


@define
class Blacklodge_Image_For_Stratos(object):
    blacklodge_model: Blacklodge_Model = field()
    blacklodge_user: Blacklodge_User = field()
    aws_accounts_for_blacklodge: AWS_Accounts_For_Blacklodge = field()
    stratos_application_values: Stratos_Application_Values = field()
    splunk_constants: Splunk_Constants = field()
    # helm_repo_deployer: Helm_Repo_Deployer = field()
    image_tag: Optional[str] = field(default=None)

    def initialize_latent_values(self):
        self._assign_git_image_tag()

    def print_me(self):
        print(asdict(self))

    def get_domain_to_host_on(self):
        clean_environment = self.stratos_application_values.get_environment().value
        return f"mlcore-{clean_environment}.apps.{clean_environment}.stratos.prci.com"
        #return f"blacklodge.apps.{clean_environment}.stratos.prci.com"

    def _get_value_from_result(self, input_result: Result[str, str], msg_tag: str):
        if input_result.is_ok:
            blacklodge_container_repo_hash = input_result.ok_value
            return blacklodge_container_repo_hash
        elif input_result.err_value:
            raise Exception(
                f"Error while getting hash for {msg_tag}: {input_result.err_value}"
            )
        else:
            raise Exception(f"Unknown Error while getting hash for {msg_tag}")

    def get_blacklodge_container_repo_hash(self) -> str:
        blacklodge_container_repo_hash_result = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.get_commit_sha()
        )
        blacklodge_container_repo_hash = self._get_value_from_result(
            blacklodge_container_repo_hash_result,
            self.blacklodge_model.runtime_config.blacklodge_container.git_repo_address,
        )
        return blacklodge_container_repo_hash

    def _assign_git_image_tag(self):
        blacklodge_container_repo_hash_result = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.get_commit_sha()
        )
        customer_repo_hash_result = self.blacklodge_model.git_repo.get_commit_sha()
        blacklodge_container_repo_hash = self._get_value_from_result(
            blacklodge_container_repo_hash_result,
            self.blacklodge_model.runtime_config.blacklodge_container.git_repo_address,
        )
        customer_repo_hash = self._get_value_from_result(
            customer_repo_hash_result, self.blacklodge_model.git_repo_url
        )
        customer_repo_hash = self._get_value_from_result(
            customer_repo_hash_result, self.blacklodge_model.git_repo_url
        )
        helcharts_repo_hash_result = (
            self.blacklodge_model.blacklodge_helm_charts_git_repo.get_commit_sha()
        )
        helmcharts_repo_hash = self._get_value_from_result(
            helcharts_repo_hash_result,
            self.blacklodge_model.blacklodge_helm_charts_git_repo.git_repo_url,
        )
        msg = blacklodge_container_repo_hash + customer_repo_hash + helmcharts_repo_hash
        self.image_tag = hashlib.sha1(msg.encode()).hexdigest()

    def get_docker_file_path(self):
        """
        This shud be for the blacklode_container. which wraps around the customer repo
        """
        container = (
            self.blacklodge_model.runtime_config.blacklodge_container.prebuilt_container.get_prebuilt_container()
        )
        dockerfile_path = f"./dockerfiles/{container}/Dockerfile"
        return dockerfile_path

    def get_git_branch(self):
        """
        This shud be for the blacklode_container. which wraps around the customer repo
        """
        git_branch = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.git_repo_branch
        )
        return git_branch

    def get_repository(self):
        """
        This shud be for the blacklode_container. which wraps around the customer repo
        """
        org = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.github_organization.value
        )
        repo = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.git_repo_name
        )
        return f"{org.upper() if org == 'pcdst' else org}/{repo}"

    def get_docker_context(self):
        """
        This shud be for the blacklode_container. which wraps around the customer repo
        """
        ctx = self.blacklodge_model.runtime_config.blacklodge_container.context_path
        return ctx

    def get_image_name(self):
        return f"blacklodge-{self.blacklodge_model.object_type.value}-{self.blacklodge_model.name}"

    def get_image_tags(self):
        if self.image_tag:
            return [self.image_tag]
        else:
            raise Exception(
                "Please call the 'assign_git_image_tag' on this instance after instantiating the object"
            )

    def get_git_commit_sha(self):
        """
        This shud be for the blacklode_container. which wraps around the customer repo
        """
        res = (
            self.blacklodge_model.runtime_config.blacklodge_container.github_repo.get_commit_sha()
        )
        if is_ok(res):
            return res.ok_value
        elif is_err(res):
            raise Exception("Error getting git commit sha " + res.err_value)
        else:
            raise Exception("Unknown error while getting git commit sha")

    def get_namespace(self):
        return self.blacklodge_user.get_namespace()

    def get_injected_aws_role_arn(self):
        return "arn:aws:iam::004782836026:role/k8s-sa-mlcore-tgw-kaniko_build"

    def get_injected_aws_account_short_alias(self):
        return "aws0gd"

    def get_registries(self):
        return ["ecr"]

    def get_git_fetch_depth(self):
        return 1

    def get_build_args(self):
        build_args = {}
        build_args["PIPELINE_NAME"] = self.blacklodge_model.name
        build_args["PIPELINE_VERSION"] = str(self.blacklodge_model.version)
        build_args["APP_TYPEE"] = self.blacklodge_model.object_type.value
        build_args["AWS_ACCOUNT_NUM"] = self.aws_accounts_for_blacklodge.aws_account_num
        build_args["PYTHON_VERSION"] = self.blacklodge_model.python_version
        build_args["BLACKLODGE_PIPELINE_REPO_HASH"] = "something"
        build_args["BLACKLODGE_CONTAINER_REPO_HASH"] = "something"
        build_args["BLACKLODGE_HELM_CHART_REPO_HASH"] = "something"
        # if self.linux_template:
        #    build_args["LINUX_TEMPLATE"] = self.linux_template
        return build_args

    def get_ecr_image_path(
        self,
    ):
        image_name = self.get_image_name()
        image_tag = self.get_image_tags()[0]
        return f"{self.aws_accounts_for_blacklodge.ecr_account}.dkr.ecr.us-east-1.amazonaws.com/internal/containerimages/{self.stratos_application_values.platform}/{self.get_namespace()}/{image_name}:{image_tag}"


@define
# name this Blacklodge_Helm_Chart_Reference
class Helm_Repo_Deployer(object):
    helm_chart_type: Blacklodge_Helm_Chart_Type = field()
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()
    chart_version_getter: HelmChart_Version_Getter = field(
        default=HelmChart_Version_Hardcoded_Getter()
    )

    def _get_chart_version(self):
        return self.chart_version_getter.versions[self.helm_chart_type]

    def _get_dependencies_list(self):
        stratos_application_values = (
            self.blacklodge_image_for_stratos.stratos_application_values
        )
        dependencies_list = [
            {
                "name": self.helm_chart_type.value,
                "version": self._get_chart_version(),
                "repository": stratos_application_values.helm_repositry,
            }
        ]
        return dependencies_list

    def _get_chart_content(self):
        chart_dict = {
            "apiVersion": "v2",
            "name": self.helm_chart_type.value,
            "description": f"Auto-generated template for {self.helm_chart_type.value}",
            "type": "application",
            "version": "1.0.0",
            "appVersion": "1.0.0",
            "dependencies": self._get_dependencies_list(),
        }
        return chart_dict

    def _get_values_content_for_pipeline(
        self,
    ):
        """
        Generates a helm values.yaml string from the provided inputs
        """
        blacklodge_model = self.blacklodge_image_for_stratos.blacklodge_model
        blacklodge_user = self.blacklodge_image_for_stratos.blacklodge_user
        namespace = blacklodge_user.get_teamname()

        ## Generating yaml file for helm values
        image_path = self.blacklodge_image_for_stratos.get_ecr_image_path()
        image_dict = {"path": image_path}

        resources_dict = {
            "limits": {
                "cpu": str(blacklodge_model.runtime_config.max_cpu),
                "memory": f"{int(blacklodge_model.runtime_config.max_memory_mb)}M",
            },
            "requests": {
                "cpu": str(blacklodge_model.runtime_config.min_cpu),
                "memory": f"{int(blacklodge_model.runtime_config.min_memory_mb)}M",
            },
        }

        host_list = [
            {
                "host": self.blacklodge_image_for_stratos.get_domain_to_host_on(),
                "paths": [
                    {
                        "path": f"/v1/pipelines/{blacklodge_model.name}/versions/{blacklodge_model.version}",
                        "pathType": "Prefix",
                    }
                ],
            },
        ]

        ingress_dict = {"hosts": host_list}

        values_yaml_dict = {
            self.helm_chart_type.value: {
                "replicaCount": str(blacklodge_model.runtime_config.replicas),
                "fullnameOverride": f"{blacklodge_model.name}-{blacklodge_model.version}",
                "environment": self.blacklodge_image_for_stratos.stratos_application_values.get_environment().value,
                "splunk_environment": self.blacklodge_image_for_stratos.splunk_constants.environment,
                "containerName": f"{blacklodge_model.name}-{blacklodge_model.version}",
                "image": image_dict,
                "resources": resources_dict,
                "ingress": ingress_dict,
                "envvars": [],
            }
        }

        if blacklodge_model.runtime_config.minimum_replicas > 0:
            autoscaling_dict = {
                "enabled": True,
                "minReplicas": blacklodge_model.runtime_config.minimum_replicas,
                "maxReplicas": blacklodge_model.runtime_config.maximum_replicas,
                "targetCPUUtilizationPercentage": str(
                    blacklodge_model.runtime_config.target_cpu_utilization
                ),
                "targetMemoryUtilizationPercentage": str(
                    blacklodge_model.runtime_config.target_memory_utilization
                ),
            }
            values_yaml_dict[self.helm_chart_type.value][
                "autoscaling"
            ] = autoscaling_dict

        if blacklodge_model.runtime_config.inputs:
            values_yaml_dict[self.helm_chart_type.value][
                "envvars"
            ] = blacklodge_model.runtime_config.inputs

        ### OTEL Default variable
        values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
            {
                "name": "OTEL_RESOURCE_ATTRIBUTES",
                "value": f"service.name=MLCore - {blacklodge_model.name}, service.namespace={namespace}, service.version={blacklodge_model.version}",
            }
        )

        if not blacklodge_model.runtime_config.otel_tracing:
            otel_dict = {"enabled": False}
            values_yaml_dict[self.helm_chart_type.value]["monitoring"] = {
                "otel": otel_dict
            }
            values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
                {"name": "OTEL_TRACES_SAMPLER", "value": "always_off"}
            )

        else:
            values_yaml_dict[self.helm_chart_type.value]["envvars"].append(
                {"name": "OTEL_TRACES_SAMPLER", "value": "always_on"}
            )

        return values_yaml_dict

    def _get_values_content_for_alias(self, model_name, pipeline_alias: Pipeline_Alias):
        """
        Generates a helm values.yaml string from the provided inputs
        """
        ingress_dict = {"enabled": True}
        values_yaml_dict = {
            self.helm_chart_type.value: {
                "modelName": model_name,
                "modelVersion": pipeline_alias.version,
                "aliasName": pipeline_alias.alias,
                "environment": self.blacklodge_image_for_stratos.stratos_application_values.get_environment().value,
                "modelPort": 8081,
                "ingress" : ingress_dict
            }
        }
        return values_yaml_dict

    def _get_values_content_for_namespace(self):
        return None


@define
class Stratos_ContainerBuild_V1_Data_Builder_Interface(ABC):

    @abstractmethod
    def construct_containerbuild_metadata(self) -> Stratos_ContainerBuild_Metadata_V1:
        pass


@define
class Stratos_ContainerBuild_V1_Data_Builder_From_Blacklodge_Image(
    Stratos_ContainerBuild_V1_Data_Builder_Interface
):
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()

    def construct_containerbuild_metadata(self) -> Stratos_ContainerBuild_Metadata_V1:
        return Stratos_ContainerBuild_Metadata_V1(
            repository=self.blacklodge_image_for_stratos.get_repository(),
            git_branch=self.blacklodge_image_for_stratos.get_git_branch(),
            git_commit_sha=self.blacklodge_image_for_stratos.get_git_commit_sha(),
            image_name=self.blacklodge_image_for_stratos.get_image_name(),
            dockerfile_path=self.blacklodge_image_for_stratos.get_docker_file_path(),
            docker_context=self.blacklodge_image_for_stratos.get_docker_context(),
            namespace=self.blacklodge_image_for_stratos.get_namespace(),
            image_tags=self.blacklodge_image_for_stratos.get_image_tags(),
            injected_aws_role_arn=self.blacklodge_image_for_stratos.get_injected_aws_role_arn(),
            injected_aws_account_short_alias=self.blacklodge_image_for_stratos.get_injected_aws_account_short_alias(),
            registries=self.blacklodge_image_for_stratos.get_registries(),
            build_args=self.blacklodge_image_for_stratos.get_build_args(),
            git_fetch_depth=self.blacklodge_image_for_stratos.get_git_fetch_depth(),
        )


@define
class Stratos_Deployer_V1_Data_Interface(ABC):
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()

    def get_stratos_appownersmetadata_v1(
        self, application_name
    ) -> Stratos_AppOwnersMetadata_V1:
        stratos_application_metadata = Stratos_AppOwnersMetadata_V1(
            repository=self.blacklodge_image_for_stratos.blacklodge_model.git_repo.git_repo_name,
            repository_url=self.blacklodge_image_for_stratos.blacklodge_model.git_repo.git_repo_url,
            application_contact=self.blacklodge_image_for_stratos.blacklodge_model.user_email[
                0
            ],
            application_name=application_name,
        )
        return stratos_application_metadata

    def get_stratos_namespacemetadata_v1(self) -> Stratos_NamespaceMetadata_V1:
        namespace_metadata = Stratos_NamespaceMetadata_V1(
            environment_name=self.get_stratos_environment(),
            application_name=self.get_stratos_application_name(),
            namespace_identifier=self.get_stratos_namespace_name(),
            project_identifier=self.get_stratos_project_identifier(),
        )
        return namespace_metadata

    def get_stratos_containerheldeployrequest_v1(
        self,
    ) -> Stratos_ContainerHelDeployRequest_V1:
        helm_data = Stratos_ContainerHelDeployRequest_V1(
            base64_chart_yaml_contents=self.get_chart_yaml_contents(),
            base64_values_yaml_contents=self.get_value_yaml_contents(),
            environment_name=self.get_stratos_environment(),
            application_name=self.get_stratos_application_name(),
            namespace_identifier=self.get_stratos_namespace_name(),
            project_identifier=self.get_stratos_project_identifier(),
        )
        return helm_data

    def get_stratos_appsyncargorequest_v1(self) -> Stratos_AppSyncArgoRequest_V1:
        app_sync_request = Stratos_AppSyncArgoRequest_V1(
            environment_name=self.get_stratos_environment(),
            application_name=self.get_stratos_application_name(),
            project_identifier=self.get_stratos_project_identifier(),
        )
        return app_sync_request

    def get_stratos_projectmetadata_v1(self) -> Stratos_ProjectMetadata_V1:
        project_metadata = Stratos_ProjectMetadata_V1(
            environment_name=self.get_stratos_environment(),
            application_name=self.get_stratos_application_name(),
            project_identifier=self.get_stratos_project_identifier(),
        )
        return project_metadata

    @abstractmethod
    def get_stratos_application_name(self) -> str:
        pass

    @abstractmethod
    def get_stratos_namespace_name(
        self,
    ):
        pass

    def get_stratos_platform(self) -> str:
        return (
            self.blacklodge_image_for_stratos.stratos_application_values.get_platform()
        )

    def get_stratos_environment(self) -> str:
        return (
            self.blacklodge_image_for_stratos.stratos_application_values.get_environment()
        )

    @abstractmethod
    def get_stratos_project_identifier(self) -> str:
        pass

    def get_stratos_account_id(self) -> str:
        return self.blacklodge_image_for_stratos.stratos_application_values.account_id

    def get_stratos_cluster_type(self) -> str:
        return self.blacklodge_image_for_stratos.stratos_application_values.allowed_cluster_types[
            0
        ]

    @abstractmethod
    def get_chart_yaml_contents(self):
        pass

    @abstractmethod
    def get_value_yaml_contents(self):
        pass

    def get_stratos_containerhelm_deployrequest_v1(
        self,
    ) -> Stratos_ContainerHelDeployRequest_V1:
        helm_data = Stratos_ContainerHelDeployRequest_V1(
            base64_chart_yaml_contents=self.get_chart_yaml_contents(),
            base64_values_yaml_contents=self.get_value_yaml_contents(),
            environment_name=self.get_stratos_environment(),
            application_name=self.get_stratos_application_name(),
            namespace_identifier=self.get_stratos_namespace_name(),
            project_identifier=self.get_stratos_project_identifier(),
        )
        return helm_data


@define
class Blacklodge_Pipeline_Deployer_Data(Stratos_Deployer_V1_Data_Interface):
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()
    helmchart_version_getter: HelmChart_Version_Getter = field(
        default=HelmChart_Version_Hardcoded_Getter()
    )
    helm_chart: Helm_Repo_Deployer = field(init=False)

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.PIPELINE
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            blacklodge_image_for_stratos=self.blacklodge_image_for_stratos,
            chart_version_getter=self.helmchart_version_getter,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_image_for_stratos.blacklodge_model.name}-{self.blacklodge_image_for_stratos.blacklodge_model.version}"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_image_for_stratos.blacklodge_user.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_image_for_stratos.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        value_content = self.helm_chart._get_values_content_for_pipeline()
        value_yaml = yaml.dump(value_content)
        return base64.urlsafe_b64encode(value_yaml.encode()).decode()


@define
class Blacklodge_Alias_Deployer_Data(Stratos_Deployer_V1_Data_Interface):
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()
    pipeline_alias: Pipeline_Alias = field()
    helm_chart: Helm_Repo_Deployer = field(init=False)
    helmchart_version_getter: HelmChart_Version_Getter = field(
        default=HelmChart_Version_Hardcoded_Getter()
    )

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.ALIAS
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            blacklodge_image_for_stratos=self.blacklodge_image_for_stratos,
            chart_version_getter=self.helmchart_version_getter,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_image_for_stratos.blacklodge_model.name}-{self.pipeline_alias.alias}"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_image_for_stratos.blacklodge_user.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_image_for_stratos.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        value_content = self.helm_chart._get_values_content_for_alias(
            self.blacklodge_image_for_stratos.blacklodge_model.name, self.pipeline_alias
        )
        value_yaml = yaml.dump(value_content)
        return base64.urlsafe_b64encode(value_yaml.encode()).decode()


@define
class Blacklodge_Namespace_Deployer_Data(Stratos_Deployer_V1_Data_Interface):
    blacklodge_image_for_stratos: Blacklodge_Image_For_Stratos = field()
    helm_chart: Helm_Repo_Deployer = field(init=False)
    helmchart_version_getter: HelmChart_Version_Getter = field(
        default=HelmChart_Version_Hardcoded_Getter()
    )

    def __attrs_post_init__(self):
        helm_chart_type = Blacklodge_Helm_Chart_Type.ALIAS
        self.helm_chart = Helm_Repo_Deployer(
            helm_chart_type=helm_chart_type,
            blacklodge_image_for_stratos=self.blacklodge_image_for_stratos,
            chart_version_getter=self.helmchart_version_getter,
        )

    def get_stratos_application_name(self) -> str:
        return f"{self.blacklodge_image_for_stratos.blacklodge_user.get_teamname()}-ns"

    def get_stratos_namespace_name(
        self,
    ):
        return self.blacklodge_image_for_stratos.get_namespace()

    def get_stratos_project_identifier(self) -> str:
        return self.blacklodge_image_for_stratos.blacklodge_user.get_teamname()

    def get_chart_yaml_contents(self):
        chart_content = self.helm_chart._get_chart_content()
        chart_yaml = yaml.dump(chart_content)
        return base64.urlsafe_b64encode(chart_yaml.encode()).decode()

    def get_value_yaml_contents(self):
        return None
