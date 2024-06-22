from __future__ import annotations
from abc import ABC
from logging import Logger
from result import Err, Ok, Result, is_ok, is_err
import time
import requests
from typing import Callable, Optional, Tuple, Any, Dict
from attrs import define, field, asdict

from mlcore_utils.model.common import (
    Http_Method,
    Secret_Getter,
    Blacklodge_Action_Status,
)
from mlcore_utils.model.blacklodge import (
    Blacklodge_Model,
    Blacklodge_User,
)

from mlcore_utils.model.common import Secret_Getter


@define
class Requests_Wrapper(object):
    # logger: Logger = field()

    def call_end_point(
        self,
        http_method: Http_Method,
        endpoint: str,
        params=None,
        data=None,
        headers=None,
        json=None,
        timeout: int = 15,
        attempt_count: int = 1,
        retries: int = 3,
        **kwargs,
    ) -> requests.Response:
        # self.logger.info("calling end point " + endpoint)
        if attempt_count > retries:
            raise Exception(
                f"Could not reach endpoint {endpoint} after {retries} attempts"
            )
        try:
            # self.logger.info("calling " + endpoint)
            return requests.request(
                method=http_method.value,
                url=endpoint,
                params=params,
                data=data,
                headers=headers,
                json=json,
                timeout=timeout,
                **kwargs,
            )
        except requests.exceptions.ReadTimeout:
            # self.logger.error(f"retry attempt {attempt_count} for endpoint {endpoint}")
            return self.call_end_point(
                http_method,
                endpoint,
                params,
                data,
                headers,
                json,
                timeout,
                attempt_count + 1,
                **kwargs,
            )
        except Exception as e:
            # self.logger.error("error calling endpoint {endpoint}")
            raise e

    def call_url_till_condition_is_met(
        self,
        status_response_url: str,
        action_to_perform,
        condition_to_meet: Callable[[requests.Response], bool],
    ) -> Result[requests.Response, str]:
        finished = False
        seconds_to_wait = 60
        num_attempt = 0
        while not (finished or num_attempt > 30):
            try:
                # status_response = self.call_api(
                #    http_method=Http_Method.GET,
                #    endpoint=f"{status_response_url}",
                # )
                status_response = action_to_perform()
                if status_response.status_code == 200:
                    condition_is_met = condition_to_meet(status_response)
                    if condition_is_met:
                        finished = True
                        return Ok(status_response)
                    else:
                        time.sleep(seconds_to_wait)
                        num_attempt = num_attempt + 1
                else:
                    time.sleep(seconds_to_wait)
                    num_attempt = num_attempt + 1
            except Exception as e:
                raise e
                # return Err(f"Cound not get status from {status_response_url}. Error {str(e)}")


class ArgoCD_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        requests_wrapper: Requests_Wrapper,
    ):
        self.secret_getter = secret_getter
        self.version = 1
        self.argocd_url = f"https://argocd.mgmt.stratos.prci.com/api/v{self.version}"
        self.requests_wrapper = requests_wrapper

    def get_default_headers(self):
        secret_result = self.secret_getter.get_secret()
        if is_ok(secret_result):
            return {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {secret_result.ok_value.get_secret_value()}",
            }
        elif is_err(secret_result):
            raise Exception(
                "error getting secret for strator API: " + secret_result.err_value
            )
        else:
            raise Exception("Unknown error getting secret for Stratos API")

    def call_api(
        self,
        http_method: Http_Method,
        endpoint: str,
        json_data=None,
        data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
        **kwargs,
    ) -> requests.Response:
        try:
            url = f"{self.argocd_url}/{endpoint}"
            response = self.requests_wrapper.call_end_point(
                http_method=http_method,
                endpoint=url,
                params=params,
                data=data,
                headers=self.get_default_headers(),
                json=json_data,
                timeout=timeout,
                attempt_count=current_attempt_count,
                retries=max_number_of_attempts,
                **kwargs,
            )
            return response
        except Exception as e:
            raise e

    def call_status_url_and_await(
        self, status_response_url
    ) -> Result[requests.Response, str]:
        condition_to_meet = lambda status_response: status_response.json()["status"][
            "health"
        ]["status"]

        def _a():
            return self.call_api(
                http_method=Http_Method.GET, endpoint=status_response_url
            )

        return self.requests_wrapper.call_url_till_condition_is_met(
            status_response_url, _a, condition_to_meet
        )


class Stratos_Api_Caller(object):
    def __init__(
        self,
        secret_getter: Secret_Getter,
        requests_wrapper: Requests_Wrapper,
    ) -> None:
        self.secret_getter = secret_getter
        self.stratos_url = f"https://jetstreamapi.apps.stratos.prci.com/api/v1/stratos"
        self.requests_wrapper = requests_wrapper

    def get_default_stratos_headers(self):
        secret_result = self.secret_getter.get_secret()
        if is_ok(secret_result):
            return {
                "accept": "application/json",
                "access_token": secret_result.ok_value.get_secret_value(),
                "Content-Type": "application/json",
            }
        elif is_err(secret_result):
            raise Exception(
                "error getting secret for strator API: " + secret_result.err_value
            )
        else:
            raise Exception("Unknown error getting secret for Stratos API")

    def call_api(
        self,
        http_method: Http_Method,
        endpoint: str,
        json_data=None,
        data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
        **kwargs,
    ) -> requests.Response:
        try:
            url = f"{self.stratos_url}/{endpoint}"
            response = self.requests_wrapper.call_end_point(
                http_method=http_method,
                endpoint=url,
                params=params,
                data=data,
                headers=self.get_default_stratos_headers(),
                json=json_data,
                timeout=timeout,
                attempt_count=current_attempt_count,
                retries=max_number_of_attempts,
                **kwargs,
            )
            return response
        except Exception as e:
            raise e

    def call_status_url_and_await(
        self, status_response_url
    ) -> Result[requests.Response, str]:
        condition_to_meet = (
            lambda status_response: status_response.json()["build_status"]
            == "completed"
        )

        def _a():
            r = self.call_api(http_method=Http_Method.GET, endpoint=status_response_url)
            print(r.status_code)
            print(r.text)
            return r

        response = self.requests_wrapper.call_url_till_condition_is_met(
            status_response_url, _a, condition_to_meet
        )
        if is_ok(response):
            print(response.ok_value.status_code)
        elif is_err(response):
            print(response.err_value)
        else:
            print("....")
        return response

    def call_api_old(
        self,
        http_method: Http_Method,
        endpoint: str,
        json_data=None,
        timeout: int = 15,
        current_attempt_count: int = 1,
        max_number_of_attempts: int = 3,
        params=None,
    ):
        if (
            current_attempt_count <= max_number_of_attempts
            if max_number_of_attempts
            else self.number_of_retries
        ):
            try:
                url = f"{self.stratos_url}/{endpoint}"
                if http_method == Http_Method.POST:
                    response = requests.post(
                        url=url,
                        json=json_data,
                        headers=self.get_default_stratos_headers(),
                        timeout=timeout,
                        # verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                elif http_method == Http_Method.GET:
                    response = requests.get(
                        url=url,
                        json=json_data,
                        params=params,
                        headers=self.get_default_stratos_headers(),
                        timeout=timeout,
                        # verify="/etc/ssl/certs/ca-certificates.crt",
                    )
                    return response
                else:
                    raise Exception(
                        "No implementation for http_method " + http_method.value
                    )
            except requests.exceptions.ReadTimeout:
                return self.call_api(
                    http_method,
                    endpoint,
                    json_data,
                    timeout,
                    current_attempt_count + 1,
                    max_number_of_attempts,
                )
            except Exception as e:
                # should we do something else?
                raise e
        else:
            raise Exception(
                f"Could not reach endpoint {endpoint} after {max_number_of_attempts} attempts"
            )

    def call_status_url_and_await_old(self, status_response_url):
        finished = False
        seconds_to_wait = 60
        num_attempt = 0
        while not (finished or num_attempt > 30):
            # status_response = requests.get(url = f"{self.stratos_url}\\{status_response_url}", headers = self.get_default_stratos_headers())
            status_response = self.call_api(
                http_method=Http_Method.GET,
                endpoint=f"{status_response_url}",
            )
            if status_response.status_code == 200:
                status = status_response.json()["build_status"]
                print("Current status " + status)
                if status.lower() == "completed":
                    conclusion = (
                        status_response.json()["conclusion"]
                        if "conclusion" in status_response.json()
                        else "..."
                    )
                    print("finished with " + conclusion)
                    finished = True
                    return status_response
                else:
                    time.sleep(seconds_to_wait)
                    num_attempt = num_attempt + 1
            else:
                time.sleep(seconds_to_wait)
                num_attempt = num_attempt + 1

        if not finished:
            raise TimeoutError(
                f"Could not get status from {status_response_url} after {num_attempt * seconds_to_wait} seconds"
            )

    def call_api_and_await_status(
        self,
        http_method: Http_Method,
        url: str,
        json_data,
        status_for_action: str,
        keyword_status_is_based_on: str,
        timeout: int = 15,
        backoff: int = 0,
    ) -> Tuple[requests.Response, Optional[requests.Response]]:
        response = self.call_api(http_method, url, json_data, timeout, backoff)
        if response.status_code == 200:
            status_keyword_value = response.json()[keyword_status_is_based_on]
            status_response_url = (
                f"{status_for_action}/{status_keyword_value}/run-status"
            )
            return (response, self.call_status_url_and_await(status_response_url))
        else:
            return (response, None)
