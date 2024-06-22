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

    def build_container(self, containerbuild_data: Stratos_ContainerBuild_Metadata_V1):
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
            self.stratos_api_caller.call_status_url_and_await(status_response_url)
    
    def create_k8s_namespace(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling k8s namespce....")
        namespace_metadata = Stratos_NamespaceMetadata_V1(
            environment_name=deployer_data.get_stratos_environment(),
            application_name=deployer_data.get_stratos_application_name(),
            namespace_identifier=deployer_data.get_stratos_namespace_name(),
            project_identifier=deployer_data.get_stratos_project_identifier(),
        )
        util.create_k8s_namespace_using_stratos_sdk(namespace_metadata)

    def create_project(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, util: Stratos_Api_V1_Util
    ):
        print("handling argocd project....")
        project_metadata = Stratos_ProjectMetadata_V1(
            environment_name=deployer_data.get_stratos_environment(),
            application_name=deployer_data.get_stratos_application_name(),
            project_identifier=deployer_data.get_stratos_project_identifier(),
        )
        argocd_proeject_result = util.create_argocd_project_using_stratos_sdk(
            project_metadata
        )
        return argocd_proeject_result

    def deploy_application(
        self, deployer_data: Stratos_Deployer_V1_Data_Interface, util: Stratos_Api_V1_Util
    ):
        self.create_k8s_namespace(deployer_data, util)
        argocd_proeject_result = self.create_project(deployer_data, util)
        if is_ok(argocd_proeject_result):
            if argocd_proeject_result.ok_value:
                # now create a stratos appowners metadata object
                print("handling s5s application....")
                stratos_application_metadata = (
                    Stratos_AppOwnersMetadata_V1.get_data_using_blacklodge_model(
                        blacklodge_model=self.blacklodge_model,
                        application_name=deployer_data.get_stratos_application_name(),
                    )
                )
                stratos_application_result = util.create_stratos_application(
                    stratos_application_metadata
                )
                if is_ok(stratos_application_result):
                    print("handling helm chart and values....")
                    helm_data = Stratos_ContainerHelDeployRequest_V1(
                        base64_chart_yaml_contents=deployer_data.get_chart_yaml_contents(),
                        base64_values_yaml_contents=deployer_data.get_value_yaml_contents(),
                        environment_name=deployer_data.get_stratos_environment(),
                        application_name=deployer_data.get_stratos_application_name(),
                        namespace_identifier=deployer_data.get_stratos_namespace_name(),
                        project_identifier=deployer_data.get_stratos_project_identifier(),
                    )
                    if deployer_data.get_value_yaml_contents():
                        deploy_result = util.deploy_helm_chart_and_values(helm_data)
                    else:
                        deploy_result = util.deploy_helm_chart(helm_data)

                    if is_ok(deploy_result):
                        helm_deploy_success = deploy_result.ok_value
                        if helm_deploy_success:
                            print(f"handling argocd app sync...")
                            app_sync_request = Stratos_AppSyncArgoRequest_V1(
                                environment_name=deployer_data.get_stratos_environment(),
                                application_name=deployer_data.get_stratos_application_name(),
                                project_identifier=deployer_data.get_stratos_project_identifier(),
                            )
                            util.sync_argocd_application(app_sync_request)
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

    def deploy_pipeline(self):
        self.deploy_namespace()
        util = Stratos_Api_V1_Util(self.stratos_api_caller)

        deployer_data = Blacklodge_Pipeline_Deployer_Data(
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
            blacklodge_model=self.blacklodge_model,
            blacklodge_user=self.blacklodge_user,
        )
        print(
            f"Deploying ArgoCD Application for Pipeline {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data, util)

    def deploy_alias(self):
        self.deploy_namespace()
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
            self.deploy_application(deployer_data, util)

    def deploy_namespace(self):
        util = Stratos_Api_V1_Util(self.stratos_api_caller)
        deployer_data = Blacklodge_Namespace_Deployer_Data(
            stratos_application_values=self.stratos_application_values,
            aws_constants=self.aws_constants,
            splunk_constants=self.splunk_constants,
            blacklodge_model=self.blacklodge_model,
            blacklodge_user=self.blacklodge_user,
        )
        print(
            f"Deploying ArgoCD Application for Namespace {deployer_data.get_stratos_application_name()}..."
        )
        self.deploy_application(deployer_data, util)
