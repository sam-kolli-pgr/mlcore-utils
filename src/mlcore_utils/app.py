import logging
import os
import pytest

from mlcore_utils.model.common import Http_Method, MLCore_Secret
from mlcore_utils.model.blacklodge import (
    Blacklodge_BusinessUnit,
    Blacklodge_Model,
    Blacklodge_User,
)
from mlcore_utils.model.gh import GitHub_Repo, GitHub_Auth
from mlcore_utils.model.aws import (
    AWS_Accounts_For_Blacklodge,
    AWS_Credentials,
    AWS_Default_Credentials,
    AWS_S3_Util,
    AWS_SecretsManager_Secret_Getter,
    AWS_System_Manager,
    AWS_Utils,
    PGR_STS_Credentials,
)
from mlcore_utils.model.opa import get_opa_handler_env_based
from result import is_ok, is_err

from mlcore_utils.model.stratos import (
    ArgoCD_Api_Caller,
    ArgoCD_Util,
    Container_Build_Data_For_Stratos_Api_V1,
    Container_Deploy_Data_For_Stratos_Api_V1,
    Splunk_Constants,
    Stratos_Api_Caller,
    Stratos_Api_V1_Blacklodge_Application_Deployer,
    Stratos_Api_V1_Container_Builder,
    Stratos_Api_V1_Container_Deployer,
    Stratos_Application_Values,
    Stratos_Application_Values_ForAlias,
)


import requests


logger = logging.getLogger(__name__)


def register_v2(access_token):
    pass


def register(access_token):
    USER_POOL_ID_PARAM_NAME = "user_pool_id"
    AWS_SECMGR_GH_SECRET_ID = "mlcore-infra"
    AWS_SECMGR_GH_SECRET_KEY = "access_token"
    GH_SERVICE_ACCOUNT = "gh_service_account"
    STRATOS_SECRET_NAME = "stratos_api_key"
    STRATOS_SECRET_KEY = "API_KEY"
    blacklodge_file = "../../tests/resources/a123662_testpipeline/Blacklodgefile"

    creds: AWS_Credentials = AWS_Credentials.inject_aws_credentials(logger)
    ssm_util = AWS_System_Manager(creds, logger)
    gh_secrets_getter = AWS_SecretsManager_Secret_Getter(
        creds, AWS_SECMGR_GH_SECRET_ID, AWS_SECMGR_GH_SECRET_KEY, logger
    )
    gh_service_account_result = ssm_util.get_parameter_value(GH_SERVICE_ACCOUNT)
    if is_err(gh_service_account_result):
        print(gh_service_account_result.err_value)
        raise Exception(gh_service_account_result.err_value)

    if is_ok(gh_service_account_result):
        github_auth = GitHub_Auth.get_from_username_and_secret_getter(
            gh_service_account_result.ok_value, gh_secrets_getter
        )
        blacklodge_model = Blacklodge_Model.from_toml_file(blacklodge_file, github_auth)
        opa_handler = get_opa_handler_env_based(logger)

        user_pool_id_result = ssm_util.get_parameter_value(USER_POOL_ID_PARAM_NAME)
        if is_err(user_pool_id_result):
            raise Exception("Could not find User Pool Id in AWS SSM")
        aws_util_for_cognito = AWS_Utils(creds, "cognito-idp", logger)
        user = Blacklodge_User.create_from_cognito_saml_token(
            user_pool_id_result.ok_value, aws_util_for_cognito, access_token
        )
        user_has_permission = opa_handler.does_user_have_permission(
            user, blacklodge_model.name
        )

        if user_has_permission:
            blacklodge_aws_constants = (
                AWS_Accounts_For_Blacklodge.create_from_runtime_environment()
            )
            s3_util = AWS_S3_Util(aws_credentials=creds, logger=logger)

            blacklodge_model.git_repo.clone_repo_and_checkout()
            blacklodge_model.git_repo.get_dvc_files()
            tarfile_result = blacklodge_model.git_repo.produce_tar_ball()
            if is_ok(tarfile_result):
                file_path = tarfile_result.ok_value.name
                file_name = str(file_path).split(os.sep)[-1]
                bucket = f"{blacklodge_aws_constants.aws_account_num}-registry"
                s3_key = f"pipeline_registry/{blacklodge_model.name}/{blacklodge_model.version}/{file_name}"
                s3_util.upload_file(bucket=bucket, key=s3_key, filename=str(file_path))

                container_build_data = Container_Build_Data_For_Stratos_Api_V1(
                    blacklodge_model=blacklodge_model,
                    aws_metadata=blacklodge_aws_constants,
                    blacklodge_business_unit=user.business_unit,
                )
                stratos_secret_getter = AWS_SecretsManager_Secret_Getter(
                    credentials=creds,
                    secret_name=STRATOS_SECRET_NAME,
                    secret_key=STRATOS_SECRET_KEY,
                    logger=logger,
                )
                stratos_api_caller = Stratos_Api_Caller(
                    secret_getter=stratos_secret_getter
                )
                container_builder = Stratos_Api_V1_Container_Builder(
                    container_build_data_for_stratos_api=container_build_data,
                    stratos_api_caller=stratos_api_caller,
                )
                build_response = container_builder.build_container_image()
                print(build_response)

            elif is_err(tarfile_result):
                print("Could not get tarfile " + tarfile_result.err_value)
            else:
                print("Unknonw")
    else:
        print("User Does not permission")


def deploy(access_token, mode):

    USER_POOL_ID_PARAM_NAME = "user_pool_id"
    AWS_SECMGR_GH_SECRET_ID = "mlcore-infra"
    AWS_SECMGR_GH_SECRET_KEY = "access_token"
    GH_SERVICE_ACCOUNT = "gh_service_account"
    STRATOS_SECRET_NAME = "stratos_api_key"
    STRATOS_SECRET_KEY = "API_KEY"
    blacklodge_file = "../../tests/resources/a123662_testpipeline/Blacklodgefile"

    creds: AWS_Credentials = AWS_Credentials.inject_aws_credentials(logger)
    ssm_util = AWS_System_Manager(creds, logger)
    gh_service_account_result = ssm_util.get_parameter_value(GH_SERVICE_ACCOUNT)
    if is_err(gh_service_account_result):
        print(gh_service_account_result.err_value)
        raise Exception(gh_service_account_result.err_value)

    if is_ok(gh_service_account_result):
        gh_secrets_getter = AWS_SecretsManager_Secret_Getter(
            creds, AWS_SECMGR_GH_SECRET_ID, AWS_SECMGR_GH_SECRET_KEY, logger
        )
        github_auth = GitHub_Auth.get_from_username_and_secret_getter(
            gh_service_account_result.ok_value, gh_secrets_getter
        )
        user_pool_id_result = ssm_util.get_parameter_value(USER_POOL_ID_PARAM_NAME)
        if is_err(user_pool_id_result):
            raise Exception(
                f"Could not find param {USER_POOL_ID_PARAM_NAME} which is required to get User Pool Id"
            )
        aws_util_for_cognito = AWS_Utils(creds, "cognito-idp", logger)
        blacklodge_user = Blacklodge_User.create_from_cognito_saml_token(
            user_pool_id_result.ok_value, aws_util_for_cognito, access_token
        )

        blacklodge_model = Blacklodge_Model.from_toml_file(blacklodge_file, github_auth)
        # if mode == "deployment":
        #    stratos_api_values: Stratos_Application_Values = Stratos_Application_Values()
        # else:
        #    stratos_api_values: Stratos_Application_Values_ForAlias = Stratos_Application_Values_ForAlias()
        stratos_api_values: Stratos_Application_Values = Stratos_Application_Values()

        stratos_secret_getter = AWS_SecretsManager_Secret_Getter(
            credentials=creds,
            secret_name=STRATOS_SECRET_NAME,
            secret_key=STRATOS_SECRET_KEY,
            logger=logger,
        )
        api_caller = Stratos_Api_Caller(secret_getter=stratos_secret_getter)

        data = Container_Deploy_Data_For_Stratos_Api_V1(
            stratos_application_values=stratos_api_values,
            aws_constants=AWS_Accounts_For_Blacklodge.create_from_runtime_environment(),
            blacklodge_model=blacklodge_model,
            blacklodge_user=blacklodge_user,
            splunk_constants=Splunk_Constants(),
            bl_object=mode,
        )
        deployer = Stratos_Api_V1_Container_Deployer(
            container_deploy_data_for_stratos_api=data,
            stratos_api_caller=api_caller,
        )
        deployer.deploy_container_image()
    else:
        print("GH Service Accoutn Error")


def deploy_v2(access_token):

    USER_POOL_ID_PARAM_NAME = "user_pool_id"
    AWS_SECMGR_GH_SECRET_ID = "mlcore-infra"
    AWS_SECMGR_GH_SECRET_KEY = "access_token"
    GH_SERVICE_ACCOUNT = "gh_service_account"
    STRATOS_SECRET_NAME = "stratos_api_key"
    STRATOS_SECRET_KEY = "API_KEY"
    blacklodge_file = "../../tests/resources/a123662_testpipeline/Blacklodgefile"

    creds: AWS_Credentials = AWS_Credentials.inject_aws_credentials(logger)
    ssm_util = AWS_System_Manager(creds, logger)
    gh_service_account_result = ssm_util.get_parameter_value(GH_SERVICE_ACCOUNT)
    if is_err(gh_service_account_result):
        print(gh_service_account_result.err_value)
        raise Exception(gh_service_account_result.err_value)

    if is_ok(gh_service_account_result):
        gh_secrets_getter = AWS_SecretsManager_Secret_Getter(
            creds, AWS_SECMGR_GH_SECRET_ID, AWS_SECMGR_GH_SECRET_KEY, logger
        )
        github_auth = GitHub_Auth.get_from_username_and_secret_getter(
            gh_service_account_result.ok_value, gh_secrets_getter
        )
        user_pool_id_result = ssm_util.get_parameter_value(USER_POOL_ID_PARAM_NAME)
        if is_err(user_pool_id_result):
            raise Exception(
                f"Could not find param {USER_POOL_ID_PARAM_NAME} which is required to get User Pool Id"
            )
        aws_util_for_cognito = AWS_Utils(creds, "cognito-idp", logger)
        blacklodge_user = Blacklodge_User.create_from_cognito_saml_token(
            user_pool_id_result.ok_value, aws_util_for_cognito, access_token
        )

        blacklodge_model = Blacklodge_Model.from_toml_file(blacklodge_file, github_auth)
        stratos_application_values: Stratos_Application_Values = (
            Stratos_Application_Values()
        )

        stratos_secret_getter = AWS_SecretsManager_Secret_Getter(
            credentials=creds,
            secret_name=STRATOS_SECRET_NAME,
            secret_key=STRATOS_SECRET_KEY,
            logger=logger,
        )
        api_caller = Stratos_Api_Caller(secret_getter=stratos_secret_getter)

        deployer = Stratos_Api_V1_Blacklodge_Application_Deployer(
            stratos_application_values=stratos_application_values,
            aws_constants=AWS_Accounts_For_Blacklodge.create_from_runtime_environment(),
            splunk_constants=Splunk_Constants(),
            blacklodge_model=blacklodge_model,
            blacklodge_user=blacklodge_user,
            stratos_api_caller=api_caller,
        )
        deployer.deploy_namespace()
        deployer.deploy_pipeline()
        deployer.deploy_alias()

    else:
        print("GH Service Accoutn Error")


def argocd_test():
    ARGOCD_SECRET_NAME = "MLCore_Stratos_ArgoCD"
    ARGOCD_SECRET_KEY = "api_key"

    creds: AWS_Credentials = AWS_Credentials.inject_aws_credentials(logger)
    stratos_application_values = Stratos_Application_Values(None)
    argocd_secrets_getter = AWS_SecretsManager_Secret_Getter(
        credentials=creds,
        secret_name=ARGOCD_SECRET_NAME,
        secret_key=ARGOCD_SECRET_KEY,
        logger=logger,
    )
    argocd_api_caller = ArgoCD_Api_Caller(secret_getter=argocd_secrets_getter)
    argocd_util = ArgoCD_Util(stratos_application_values, argocd_api_caller)
    result = argocd_util.get_application_status()


def _init_reqd_objects(token):
    USER_POOL_ID_PARAM_NAME = "user_pool_id"
    AWS_SECMGR_GH_SECRET_ID = "mlcore-infra"
    AWS_SECMGR_GH_SECRET_KEY = "access_token"
    GH_SERVICE_ACCOUNT = "gh_service_account"
    STRATOS_SECRET_NAME = "stratos_api_key"
    STRATOS_SECRET_KEY = "API_KEY"
    blacklodge_file = "../../tests/resources/a123662_testpipeline/Blacklodgefile"


def _main():
    token = "eyJraWQiOiJqU2pWZlNENjdheGQ3NHZMVmhLVmxmd05HazN1eTdERTJ5SSs5ZzBJbDlvPSIsImFsZyI6IlJTMjU2In0.eyJzdWIiOiJiMTE4NzQ1ZC1lYmQ3LTQ2NjItYTQ5Ny0zMTgzOTVjYWM3OTEiLCJjb2duaXRvOmdyb3VwcyI6WyJ1cy1lYXN0LTFfYUM0NUpiYmlvX21sY29yZS1jbGllbnQtYXp1cmVhZCJdLCJpc3MiOiJodHRwczpcL1wvY29nbml0by1pZHAudXMtZWFzdC0xLmFtYXpvbmF3cy5jb21cL3VzLWVhc3QtMV9hQzQ1SmJiaW8iLCJ2ZXJzaW9uIjoyLCJjbGllbnRfaWQiOiIydDVrYnVpam9kMmE4M2w0MDhiMmFrNmlrayIsIm9yaWdpbl9qdGkiOiI5ODIxMmUyZi0wZDg2LTQyNTMtODAxOC02Y2M2OGJmMzI5OGQiLCJ0b2tlbl91c2UiOiJhY2Nlc3MiLCJzY29wZSI6Im9wZW5pZCIsImF1dGhfdGltZSI6MTcxODg0MzQwMSwiZXhwIjoxNzE4ODg2NjAxLCJpYXQiOjE3MTg4NDM0MDEsImp0aSI6IjBjN2M2MmY3LWUwODEtNDdiZi1hNmU2LTUyNGI5ZmE4MTcxZCIsInVzZXJuYW1lIjoibWxjb3JlLWNsaWVudC1henVyZWFkX1NBTV9TX0tPTExJQFByb2dyZXNzaXZlLmNvbSJ9.gkj0SnvHt3h-adBcbWLJtcvhtHjHSZpXV5fXnUP5mHKzNHhTWsGh__X1Ex_zEgaSW79LLIwXU2DRtl54mszqgKdpAqQ6hFUz1hmj1CkFRsQNyS4egEPhP2eRmoJbXR8XzjgRvEd0dAIBVI6cPXHGeLCuaa6J93BCylgvKlGxtnzsOwHeowLFnEvTJ2BC6Ix5mn72tFWyplLjE0jqVwZ-g7-EH29VvWNtyCQyuTw2m2e1ozVp-KaRi5XolkooSo-MEEzI1orZhOeWTGM4hhOWzUrlIDNzhndhLkacIPKjKXtQW6OuqEioxkQfKNZBP5Q1ZT8-LMWdFT8CYpGCf9_TZQ"
    #register(token)
    # deploy(token, "deployment")
    deploy_v2(token)
    # argocd_test()


if __name__ == "__main__":
    _main()
