import logging
import os
import pytest

from mlcore_utils.model.common import MLCore_Secret
from mlcore_utils.model.blacklodge import Blacklodge_BusinessUnit, Blacklodge_Model
from mlcore_utils.model.gh import GitHub_Repo, GitHub_Auth
from mlcore_utils.model.aws import AWS_Accounts_For_Blacklodge, AWS_Credentials, AWS_Default_Credentials, AWS_S3_Util, AWS_SecretsManager_Secret_Getter, AWS_System_Manager, PGR_STS_Credentials
from result import is_ok, is_err

from mlcore_utils.model.stratos import Container_Build_Data_For_Stratos_Api_V1, Stratos_Api_Caller, Stratos_Api_V1_Container_Builder


logger = logging.getLogger(__name__)

@pytest.fixture
def a123662_testpipeline_git_repo() -> GitHub_Repo:
    github_auth = GitHub_Auth(
        "sam-kolli-pgr", MLCore_Secret("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")
    )
    repo = GitHub_Repo.get_from_inputs(
        # git_repo_url="https://github.com/PCDST/bl_bertpipeline_dvc",
        git_repo_url="https://github.com/PCDST/a123662_testpipeline",
        git_repo_branch="skolli",
        github_auth=github_auth,
    )
    return repo

@pytest.fixture
def s3_utility() -> AWS_S3_Util:
    creds : AWS_Credentials = AWS_Default_Credentials(logger=logger)
    s3_util = AWS_S3_Util(aws_credentials=creds, logger=logger)
    return s3_util

@pytest.mark.gitactions
def test_get_from_github_and_save_to_s3(a123662_testpipeline_git_repo: GitHub_Repo):
    GH_SERVICE_ACCOUNT = "gh_service_account"
    STRATOS_SECRET_NAME  = "stratos_api_key"
    STRATOS_SECRET_KEY  = "API_KEY"
    #creds : AWS_Credentials = AWS_Default_Credentials(logger=logger)
    creds : AWS_Credentials = PGR_STS_Credentials(
        aws_account="004782836026",
        role="D-A-AWS0GD-EDS-MLCORE",
        username="a123662",
        password=MLCore_Secret(os.environ["PASSWORD"]),
        logger=logger
    )
    
    ssm_util = AWS_System_Manager(creds, logger)
    gh_secrets_getter = AWS_SecretsManager_Secret_Getter(creds, "mlcore-infra", "access_token", logger)
    gh_service_account_result = ssm_util.get_parameter_value(GH_SERVICE_ACCOUNT)
    if is_err(gh_service_account_result):
        print(gh_service_account_result.err_value)
        raise Exception(gh_service_account_result.err_value)
        #assert False

    if is_ok(gh_service_account_result):
        github_auth = GitHub_Auth.get_from_username_and_secret_getter(gh_service_account_result.ok_value, gh_secrets_getter) 

        blacklodge_model = Blacklodge_Model.from_toml_file("./tests/resources/a123662_testpipeline/Blacklodgefile", github_auth)
        pipeline_git_repo = GitHub_Repo.get_from_inputs(
            # git_repo_url="https://github.com/PCDST/bl_bertpipeline_dvc",
            git_repo_url="https://github.com/PCDST/a123662_testpipeline",
            git_repo_branch="skolli",
            github_auth=github_auth,
        )

        blacklodge_aws_constants = AWS_Accounts_For_Blacklodge.create_from_env("dev")
        s3_util = AWS_S3_Util(aws_credentials=creds, logger=logger)

        pipeline_git_repo.clone_repo_and_checkout()
        pipeline_git_repo.get_dvc_files()
        tarfile_result = pipeline_git_repo.produce_tar_ball()
        if is_ok(tarfile_result):
            file_path = tarfile_result.ok_value.name
            file_name = str(file_path).split(os.sep)[-1]
            bucket = f"{blacklodge_aws_constants.aws_account_num}-registry"
            s3_key = f"pipeline_registry/{blacklodge_model.name}/{blacklodge_model.version}/{file_name}"
            s3_util.upload_file(bucket=bucket, key=s3_key, filename=str(file_path))

            business_unit = Blacklodge_BusinessUnit(
                custom_groups = ["D-U-AWS0GD-EDS-MLCORE", "D-U-MLCORE-CLA-CC"]
            )

            container_build_data = Container_Build_Data_For_Stratos_Api_V1(
                blacklodge_model=blacklodge_model,
                aws_metadata=blacklodge_aws_constants,
                blacklodge_business_unit=business_unit
            )
            stratos_secret_getter = AWS_SecretsManager_Secret_Getter(
                credentials = creds,
                secret_name = STRATOS_SECRET_NAME,
                secret_key = STRATOS_SECRET_KEY,
                logger= logger
            )
            stratos_api_caller = Stratos_Api_Caller(secret_getter=stratos_secret_getter)
            container_builder = Stratos_Api_V1_Container_Builder(
                container_build_data_for_stratos_api=container_build_data,
                stratos_api_caller=stratos_api_caller
            ) 
            build_response = container_builder.build_container_image()
            print(build_response)


            

        elif is_err(tarfile_result):
            print("Could not get tarfile " + tarfile_result.err_value)
        else:
            print("Unknonw")

        assert False

    else:
        assert False



