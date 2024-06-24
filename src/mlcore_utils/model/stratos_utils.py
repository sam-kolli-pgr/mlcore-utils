from mlcore_utils.model.stratos_api import Stratos_Api_Caller, Stratos_Api_V1_Util
from result import Err, Ok, Result, is_ok, is_err
from attr import asdict, define, field
from mlcore_utils.model.common import Http_Method
from mlcore_utils.model.data import Blacklodge_Alias_Deployer_Data, Blacklodge_Namespace_Deployer_Data, Blacklodge_Pipeline_Deployer_Data, Stratos_Deployer_V1_Data_Interface
from mlcore_utils.model.stratos_api import Stratos_Api_Caller
from mlcore_utils.model.stratos_interface import Stratos_AppOwnersMetadata_V1, Stratos_AppSyncArgoRequest_V1, Stratos_ContainerBuild_Metadata_V1, Stratos_ContainerHelDeployRequest_V1, Stratos_NamespaceMetadata_V1, Stratos_ProjectMetadata_V1

@define
class Stratos_Util(object):
    stratos_api_caller: Stratos_Api_Caller = field()
    util : Stratos_Api_V1_Util = field(init=False)

    def __attrs_post_init__(self):
        self.util = Stratos_Api_V1_Util(self.stratos_api_caller)


    def build_container(self, containerbuild_data: Stratos_ContainerBuild_Metadata_V1) -> Result[str, str]:
        json_data = asdict(containerbuild_data)
        response = self.stratos_api_caller.call_api(
            http_method=Http_Method.POST,
            endpoint="containerbuild",
            json_data=json_data,
        )
        if response.status_code == 200:
            commit_sha = response.json()["commit_sha"]
            # status_response_url = f"{self.stratos_api_caller.stratos_url}/containerbuild/{commit_sha}/run-status"
            status_response_url = f"containerbuild/{commit_sha}/run-status"
            result = self.stratos_api_caller.call_status_url_and_await(status_response_url)
            if is_ok(result):
                if result.ok_value.status_code == 200:
                    return Ok(result.ok_value.json()["conclusion"])
                elif result.ok_value.status_code == 422:
                    return Err(f"Building container image failed with error {result.ok_value.json()['msg']}")
                else:
                    return Err(f"Building container image failed with error {result.ok_value.text}")
            elif is_err(result):
                return Err(result.err_value)
            else:
                return Err("Building container image failed with unknown error")

    def create_k8s_namespace(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling k8s namespce....")
        namespace_metadata = deployer_data.get_stratos_namespacemetadata_v1()
        util.create_k8s_namespace_using_stratos_sdk(namespace_metadata)

    def create_project(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling argocd project....")
        project_metadata = deployer_data.get_stratos_projectmetadata_v1()
        argocd_proeject_result = util.create_argocd_project_using_stratos_sdk(
            project_metadata
        )
        return argocd_proeject_result

    def deploy_application(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, 
    ):
        self.create_k8s_namespace(deployer_data, self.util)
        argocd_proeject_result = self.create_project(deployer_data, self.util)
        if is_ok(argocd_proeject_result):
            if argocd_proeject_result.ok_value:
                # now create a stratos appowners metadata object
                print("handling s5s application....")
                stratos_application_metadata = deployer_data.get_stratos_appownersmetadata_v1(deployer_data.get_stratos_application_name())
                stratos_application_result = self.util.create_stratos_application(
                    stratos_application_metadata
                )
                if is_ok(stratos_application_result):
                    print("handling helm chart and values....")
                    helm_data = deployer_data.get_stratos_containerheldeployrequest_v1()
                    if helm_data.base64_values_yaml_contents:
                        deploy_result = self.util.deploy_helm_chart_and_values(helm_data)
                    else:
                        deploy_result = self.util.deploy_helm_chart(helm_data)

                    if is_ok(deploy_result):
                        helm_deploy_success = deploy_result.ok_value
                        if helm_deploy_success:
                            print(f"handling argocd app sync...")
                            app_sync_request = deployer_data.get_stratos_appsyncargorequest_v1()
                            self.util.sync_argocd_application(app_sync_request)
                        else:
                            print("Stratos call to update helm chart/vales failed")
                    elif is_err(deploy_result):
                        print(
                            "Stratos call to update helm chart/vales failed with "
                            + deploy_result.err_value
                        )
                    else:
                        print(
                            "Stratos call to update helm chart/vales failed with unknown error"
                        )
                elif is_err(stratos_application_result):
                    print(stratos_application_result.err_value)
                else:
                    print(
                        f"Unknown Error While Creating Stratos Application {deployer_data.get_stratos_application_name()}"
                    )
        elif is_err(argocd_proeject_result):
            print(argocd_proeject_result.err_value)
        else:
            print(
                f"Unknown Error While Creating Stratos Project {deployer_data.get_stratos_project_identifier()}"
            )

    def deploy_pipeline(self, deployer_data : Blacklodge_Pipeline_Deployer_Data):
        self.deploy_namespace(deployer_data)

        print(
            f"Deploying ArgoCD Application for Pipeline {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data)


    def deploy_alias(self, deployer_data : Blacklodge_Alias_Deployer_Data):
        self.deploy_namespace(deployer_data)

        print(
            f"Deploying ArgoCD Application for Alias {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data)

    def deploy_namespace(self, deployer_data: Blacklodge_Namespace_Deployer_Data):
        print(
            f"Deploying ArgoCD Application for Namespace {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data)

    def deploy_alias_v2(self, deployer_data : Blacklodge_Alias_Deployer_Data):
        self.deploy_namespace(deployer_data)
        util = Stratos_Api_V1_Util(self.stratos_api_caller)

        for alias in self.blacklodge_model.aliases:
            deployer_data = Blacklodge_Alias_Deployer_Data(
                stratos_application_values=self.stratos_application_values,
                aws_constants=self.aws_constants,
                splunk_constants=self.splunk_constants,
                blacklodge_model=self.blacklodge_model,
                pipeline_alias=alias,
                blacklodge_user=self.blacklodge_user,
            )
            print(
                f"Deploying ArgoCD Application for Alias {deployer_data.get_stratos_application_name()}..."
            )
            self.deploy_application(deployer_data)