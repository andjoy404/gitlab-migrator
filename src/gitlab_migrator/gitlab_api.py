import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class GitLabAPI:

    def __init__(
        self,
        url,
        token,
        timeout=300,
        verify_ssl=True,
    ):

        self.url = url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()

        self.session.headers.update(
            {
                "PRIVATE-TOKEN": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        retry = Retry(
            total=5,
            connect=5,
            read=5,
            status=5,
            backoff_factor=2,
            status_forcelist=[
                429,
                500,
                502,
                503,
                504,
            ],
            allowed_methods=False,
            raise_on_status=False,
        )

        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=20,
            pool_maxsize=20,
        )

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.verify = verify_ssl

    # ==========================================================
    # INTERNAL
    # ==========================================================

    def _endpoint(self, endpoint):

        return f"{self.url}/api/v4{endpoint}"

    # ----------------------------------------------------------

    def _request(
        self,
        method,
        endpoint,
        retries=3,
        **kwargs,
    ):

        last_error = None

        for attempt in range(1, retries + 1):

            try:

                response = self.session.request(
                    method,
                    self._endpoint(endpoint),
                    timeout=self.timeout,
                    **kwargs,
                )

                response.raise_for_status()

                if response.status_code == 204:
                    return None

                if response.text == "":
                    return None

                try:
                    return response.json()

                except Exception:
                    return response.text

            except requests.exceptions.RequestException as e:

                last_error = e
                response = getattr(e, "response", None)
                status_code = (
                    response.status_code if response is not None else None
                )

                if response is not None:
                    try:
                        detail = response.json()
                    except ValueError:
                        detail = response.text.strip()

                    if detail:
                        if not isinstance(detail, str):
                            import json
                            detail = json.dumps(detail, ensure_ascii=True)

                        # Keep logs readable if a reverse proxy returns an
                        # entire HTML error page.
                        detail = detail[:2000]
                        e.args = (f"{e}; GitLab response: {detail}",)

                # Retrying validation, permission, and missing-resource
                # errors cannot succeed without changing the request.
                if (
                    status_code is not None
                    and 400 <= status_code < 500
                    and status_code != 429
                ):
                    raise

                if attempt == retries:
                    raise

                print(
                    f"[Retry {attempt}/{retries}] "
                    f"{method} {endpoint}"
                )

                time.sleep(2 * attempt)

        raise last_error

    # ----------------------------------------------------------

    def _paginate(
        self,
        endpoint,
        params=None,
    ):

        if params is None:
            params = {}

        page = 1

        result = []

        while True:

            query = dict(params)

            query["page"] = page
            query["per_page"] = 100

            response = self.session.get(
                self._endpoint(endpoint),
                params=query,
                timeout=self.timeout,
            )

            response.raise_for_status()

            data = response.json()

            if not data:
                break

            result.extend(data)

            next_page = response.headers.get(
                "X-Next-Page"
            )

            if not next_page:
                break

            page = int(next_page)

        return result

    # ----------------------------------------------------------

    @staticmethod
    def _encode(value):

        return quote(str(value), safe="")

    # ==========================================================
    # GENERAL
    # ==========================================================

    def version(self):

        return self._request(
            "GET",
            "/version",
        )

    # ----------------------------------------------------------

    def ping(self):

        try:

            self.version()

            return True

        except Exception:

            return False

    # ==========================================================
    # GROUPS
    # ==========================================================

    def list_groups(self):

        return self._paginate(
            "/groups",
        )

    # ----------------------------------------------------------

    def get_group(
        self,
        group_path,
    ):

        return self._request(
            "GET",
            f"/groups/{self._encode(group_path)}",
        )

    # ----------------------------------------------------------

    def find_group(
        self,
        group_path,
    ):

        try:

            return self.get_group(
                group_path,
            )

        except requests.HTTPError as e:

            if e.response.status_code == 404:
                return None

            raise

    # ----------------------------------------------------------

    def create_group(
        self,
        name,
        path,
        parent_id=None,
        visibility="private",
    ):

        payload = {
            "name": name,
            "path": path,
            "visibility": visibility,
        }

        if parent_id is not None:

            payload["parent_id"] = parent_id

        return self._request(
            "POST",
            "/groups",
            json=payload,
        )

    # ==========================================================
    # PROJECTS
    # ==========================================================

    def list_projects(
        self,
        group=None,
    ):

        if group:

            return self._paginate(
                f"/groups/{self._encode(group)}/projects",
                {
                    "include_subgroups": True,
                },
            )

        return self._paginate(
            "/projects",
        )

    # ----------------------------------------------------------

    def get_project(
        self,
        project_path,
    ):

        return self._request(
            "GET",
            f"/projects/{self._encode(project_path)}",
        )

    # ----------------------------------------------------------

    def find_project(
        self,
        project_path,
    ):

        try:

            return self.get_project(
                project_path,
            )

        except requests.HTTPError as e:

            if e.response.status_code == 404:
                return None

            raise

    # ----------------------------------------------------------

    def create_project(
        self,
        name,
        namespace_id,
        path=None,
        visibility="private",
    ):

        payload = {
            "name": name,
            "namespace_id": namespace_id,
            "visibility": visibility,
        }

        if path:

            payload["path"] = path

        return self._request(
            "POST",
            "/projects",
            json=payload,
        )

    # ----------------------------------------------------------

    def update_project(
        self,
        project_id,
        **kwargs,
    ):

        return self._request(
            "PUT",
            f"/projects/{project_id}",
            json=kwargs,
        )

    # ----------------------------------------------------------

    def delete_project(
        self,
        project_id,
    ):

        return self._request(
            "DELETE",
            f"/projects/{project_id}",
        )
    
        # ==========================================================
    # PROJECT VARIABLES
    # ==========================================================

    def list_project_variables(self, project_id):

        return self._paginate(
            f"/projects/{project_id}/variables"
        )

    # ----------------------------------------------------------

    def get_project_variable(
        self,
        project_id,
        key,
    ):

        return self._request(
            "GET",
            f"/projects/{project_id}/variables/{self._encode(key)}",
        )

    # ----------------------------------------------------------

    def create_project_variable(
        self,
        project_id,
        **variable,
    ):

        return self._request(
            "POST",
            f"/projects/{project_id}/variables",
            json=variable,
        )

    # ----------------------------------------------------------

    def update_project_variable(
        self,
        project_id,
        key,
        **variable,
    ):

        return self._request(
            "PUT",
            f"/projects/{project_id}/variables/{self._encode(key)}",
            json=variable,
        )

    # ----------------------------------------------------------

    def delete_project_variable(
        self,
        project_id,
        key,
    ):

        return self._request(
            "DELETE",
            f"/projects/{project_id}/variables/{self._encode(key)}",
        )

    # ==========================================================
    # GROUP VARIABLES
    # ==========================================================

    def list_group_variables(self, group_id):

        return self._paginate(
            f"/groups/{group_id}/variables"
        )

    # ----------------------------------------------------------

    def get_group_variable(
        self,
        group_id,
        key,
    ):

        return self._request(
            "GET",
            f"/groups/{group_id}/variables/{self._encode(key)}",
        )

    # ----------------------------------------------------------

    def create_group_variable(
        self,
        group_id,
        **variable,
    ):

        return self._request(
            "POST",
            f"/groups/{group_id}/variables",
            json=variable,
        )

    # ----------------------------------------------------------

    def update_group_variable(
        self,
        group_id,
        key,
        **variable,
    ):

        return self._request(
            "PUT",
            f"/groups/{group_id}/variables/{self._encode(key)}",
            json=variable,
        )

    # ----------------------------------------------------------

    def delete_group_variable(
        self,
        group_id,
        key,
    ):

        return self._request(
            "DELETE",
            f"/groups/{group_id}/variables/{self._encode(key)}",
        )

    # ==========================================================
    # PROJECT HOOKS
    # ==========================================================

    def list_hooks(self, project_id):

        return self._paginate(
            f"/projects/{project_id}/hooks"
        )

    # ----------------------------------------------------------

    def create_hook(
        self,
        project_id,
        **hook,
    ):

        return self._request(
            "POST",
            f"/projects/{project_id}/hooks",
            json=hook,
        )

    # ----------------------------------------------------------

    def delete_hook(
        self,
        project_id,
        hook_id,
    ):

        return self._request(
            "DELETE",
            f"/projects/{project_id}/hooks/{hook_id}",
        )

    # ==========================================================
    # PROTECTED BRANCHES
    # ==========================================================

    def list_protected_branches(
        self,
        project_id,
    ):

        return self._paginate(
            f"/projects/{project_id}/protected_branches"
        )

    # ----------------------------------------------------------

    def protect_branch(
        self,
        project_id,
        **branch,
    ):

        return self._request(
            "POST",
            f"/projects/{project_id}/protected_branches",
            json=branch,
        )

    # ----------------------------------------------------------

    def unprotect_branch(
        self,
        project_id,
        branch_name,
    ):

        return self._request(
            "DELETE",
            f"/projects/{project_id}/protected_branches/{self._encode(branch_name)}",
        )

    # ==========================================================
    # RUNNERS
    # ==========================================================

    def list_instance_runners(self):

        return self._paginate(
            "/runners/all"
        )

    # ----------------------------------------------------------

    def list_group_runners(
        self,
        group_id,
    ):

        return self._paginate(
            f"/groups/{group_id}/runners"
        )

    # ----------------------------------------------------------

    def list_project_runners(
        self,
        project_id,
    ):

        return self._paginate(
            f"/projects/{project_id}/runners"
        )

    # ----------------------------------------------------------

    def get_runner(
        self,
        runner_id,
    ):

        return self._request(
            "GET",
            f"/runners/{runner_id}"
        )

    # ----------------------------------------------------------

    def list_runner_managers(self, runner_id):
        return self._paginate(f"/runners/{runner_id}/managers")

    # ----------------------------------------------------------

    def pause_runner(
        self,
        runner_id,
    ):

        return self._request(
            "PUT",
            f"/runners/{runner_id}",
            json={
                "paused": True,
            },
        )

    # ----------------------------------------------------------

    def resume_runner(
        self,
        runner_id,
    ):

        return self._request(
            "PUT",
            f"/runners/{runner_id}",
            json={
                "paused": False,
            },
        )

    # ----------------------------------------------------------

    def create_user_runner(
        self,
        runner_type,
        description,
        group_id=None,
        project_id=None,
        tag_list=None,
        run_untagged=False,
        locked=False,
        access_level="not_protected",
        maximum_timeout=None,
        paused=True,
    ):
        """Create a runner configuration using GitLab's current API."""

        payload = {
            "runner_type": runner_type,
            "description": description,
            "tag_list": tag_list or [],
            "run_untagged": run_untagged,
            "locked": locked,
            "access_level": access_level,
            "paused": paused,
        }

        if group_id is not None:
            payload["group_id"] = group_id

        if project_id is not None:
            payload["project_id"] = project_id

        if maximum_timeout is not None:
            payload["maximum_timeout"] = maximum_timeout

        return self._request(
            "POST",
            "/user/runners",
            json=payload,
        )

    # ----------------------------------------------------------

    def delete_runner(
        self,
        runner_id,
    ):

        return self._request(
            "DELETE",
            f"/runners/{runner_id}",
        )

    # ==========================================================
    # CONTEXT MANAGER
    # ==========================================================

    def close(self):

        self.session.close()

    # ----------------------------------------------------------

    def __enter__(self):

        return self

    # ----------------------------------------------------------

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ):

        self.close()

        # ----------------------------------------------------------

    def create_project_if_not_exists(
        self,
        name,
        path,
        namespace_id,
        visibility="private",
    ):
        """
        Return existing project if it already exists,
        otherwise create it.
        """

        #
        # Search by namespace/path
        #

        project_path = f"{namespace_id}/{path}"

        #
        # Easier approach:
        # search projects by name
        #

        projects = self._paginate(
            "/projects",
            {
                "search": path,
                "simple": True,
            },
        )

        for project in projects:

            if (
                project["path"] == path
                and project["namespace"]["id"] == namespace_id
            ):

                print("Project already exists.")

                return project

        print(f"Creating project: {name}")

        return self.create_project(
            name=name,
            path=path,
            namespace_id=namespace_id,
            visibility=visibility,
        )

    # ==========================================================
    # PIPELINES / CONTAINER REGISTRY
    # ==========================================================

    def list_merge_requests(self, project_id, **params):
        params.setdefault("scope", "all")
        params.setdefault("state", "all")
        return self._paginate(
            f"/projects/{project_id}/merge_requests",
            params,
        )

    def get_merge_request(self, project_id, merge_request_iid):
        return self._request(
            "GET",
            f"/projects/{project_id}/merge_requests/{merge_request_iid}",
        )

    def create_merge_request(self, project_id, **merge_request):
        return self._request(
            "POST",
            f"/projects/{project_id}/merge_requests",
            json=merge_request,
        )

    def update_merge_request(self, project_id, merge_request_iid, **changes):
        return self._request(
            "PUT",
            f"/projects/{project_id}/merge_requests/{merge_request_iid}",
            json=changes,
        )

    def list_merge_request_notes(self, project_id, merge_request_iid):
        return self._paginate(
            f"/projects/{project_id}/merge_requests/"
            f"{merge_request_iid}/notes",
            {"sort": "asc", "order_by": "created_at"},
        )

    def create_merge_request_note(self, project_id, merge_request_iid, **note):
        return self._request(
            "POST",
            f"/projects/{project_id}/merge_requests/"
            f"{merge_request_iid}/notes",
            json=note,
        )

    def get_branch(self, project_id, branch):
        return self._request(
            "GET",
            f"/projects/{project_id}/repository/branches/"
            f"{self._encode(branch)}",
        )

    def find_branch(self, project_id, branch):
        try:
            return self.get_branch(project_id, branch)
        except requests.HTTPError as error:
            if error.response.status_code == 404:
                return None
            raise

    def create_branch(self, project_id, branch, ref):
        return self._request(
            "POST",
            f"/projects/{project_id}/repository/branches",
            json={"branch": branch, "ref": ref},
        )

    def delete_branch(self, project_id, branch):
        return self._request(
            "DELETE",
            f"/projects/{project_id}/repository/branches/"
            f"{self._encode(branch)}",
        )

    def list_pipelines(self, project_id, status=None, **params):
        if status:
            params["status"] = status

        return self._paginate(
            f"/projects/{project_id}/pipelines",
            params or None,
        )

    def create_pipeline(self, project_id, ref):
        return self._request(
            "POST",
            f"/projects/{project_id}/pipeline",
            json={"ref": ref},
        )

    def cancel_pipeline(self, project_id, pipeline_id):
        return self._request(
            "POST",
            f"/projects/{project_id}/pipelines/{pipeline_id}/cancel",
        )

    def list_pipeline_jobs(self, project_id, pipeline_id):
        return self._paginate(
            f"/projects/{project_id}/pipelines/{pipeline_id}/jobs"
        )

    def list_project_jobs(self, project_id, statuses=None):
        params = {"scope[]": list(statuses)} if statuses else None
        return self._paginate(
            f"/projects/{project_id}/jobs",
            params,
        )

    def cancel_job(self, project_id, job_id, force=False):
        params = {"force": True} if force else None
        return self._request(
            "POST",
            f"/projects/{project_id}/jobs/{job_id}/cancel",
            params=params,
        )

    def list_registry_repositories(self, project_id):
        return self._paginate(
            f"/projects/{project_id}/registry/repositories"
        )

    def list_registry_tags(self, project_id, repository_id):
        return self._paginate(
            f"/projects/{project_id}/registry/repositories/"
            f"{repository_id}/tags"
        )

    def get_registry_tag(self, project_id, repository_id, tag_name):
        return self._request(
            "GET",
            f"/projects/{project_id}/registry/repositories/"
            f"{repository_id}/tags/{self._encode(tag_name)}",
        )

    def delete_registry_tag(self, project_id, repository_id, tag_name):
        return self._request(
            "DELETE",
            f"/projects/{project_id}/registry/repositories/"
            f"{repository_id}/tags/{self._encode(tag_name)}",
        )
