import json
from typing import Any, Dict, List, Set
from result import Err, Ok, Result, is_ok, is_err
from attr import asdict, define, field

# from mlcore_utils.model.data import Stratos_Environment


@define
class Stratos_V1_Object(object):
    def pretty_print(self):
        j = json.dumps(asdict(self), indent=4)
        print(j)


@define
class Stratos_AppOwnersMetadata_V1(Stratos_V1_Object):
    repository: str = field()
    repository_url: str = field()
    application_contact: str = field()
    application_name: str = field()
    platform: str = field(default="eds")
    allowed_cluster_types: List[str] = field(default=["blacklodge"])


@define
class Stratos_ProjectMetadata_V1(Stratos_V1_Object):
    environment_name: str = field()
    application_name: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    rendered_project_name: Any = field(init=False)

    def __attrs_post_init__(self):
        self.rendered_project_name = (
            f"{self.platform}-{self.project_identifier}-{self.environment_name.value}"
        )


@define
class Stratos_NamespaceMetadata_V1(Stratos_V1_Object):
    environment_name: str = field()
    application_name: str = field()
    namespace_identifier: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")
    account_id: str = field(default="111111")
    cluster_type: str = field(default="blacklodge")


@define
class Stratos_ContainerHelDeployRequest_V1(Stratos_V1_Object):
    base64_chart_yaml_contents: str = field()
    base64_values_yaml_contents: str = field()
    environment_name: str = field()
    application_name: str = field()
    namespace_identifier: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")
    cluster_type: str = field(default="blacklodge")


@define
class Stratos_AppSyncArgoRequest_V1(Stratos_V1_Object):
    environment_name: str = field()
    application_name: str = field()
    project_identifier: str = field()
    platform: str = field(default="eds")
    is_dynamic_environment: bool = field(default=False)
    dynamic_environment_name: str = field(default="")


@define
class Stratos_ContainerBuild_Metadata_V1(Stratos_V1_Object):
    repository: str = field()
    git_branch: str = field()
    git_commit_sha: str = field()
    image_name: str = field()
    dockerfile_path: str = field()
    docker_context: str = field()
    namespace: str = field()
    injected_aws_role_arn: str = field()
    injected_aws_account_short_alias: str = field()
    image_tags: List[str] = field(factory=list)
    registries: List[str] = field(factory=list)
    build_args: Dict[str, str] = field(factory=dict)
    git_fetch_depth: int = field(default=1)


    def validate_build_args_are_present(self, expected_build_args: Set[str]) -> Result[bool, str]:
        leftover = expected_build_args.difference(set(self.build_args.keys()))
        if len(leftover) > 0:
            return Err(f"Build Args {leftover} are expected but not supplied")
        else:
            return Ok(True)
