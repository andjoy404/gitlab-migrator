from .gitlab_api import GitLabAPI


class NamespaceManager:
    """
    Ensure destination namespace hierarchy exists.

    Example:

        appfuxion/agis/backend/api

    Returns the namespace_id of the deepest group.
    """

    def __init__(
        self,
        gitlab: GitLabAPI,
        root_group: str,
    ):
        self.gitlab = gitlab
        self.root_group = root_group.strip("/")

    # ----------------------------------------------------------

    def ensure(self, groups):
        """
        Example:

            groups = [
                "agis",
                "backend",
                "api"
            ]
        """

        #
        # Root group
        #

        root = self.gitlab.find_group(
            self.root_group
        )

        if root is None:
            raise RuntimeError(
                f"Root group '{self.root_group}' not found."
            )

        parent_id = root["id"]

        #
        # No subgroup
        #

        if not groups:
            return parent_id

        current = ""

        #
        # Walk hierarchy
        #

        for group in groups:

            if current:
                current += "/" + group
            else:
                current = group

            full_path = (
                f"{self.root_group}/{current}"
            )

            existing = self.gitlab.find_group(
                full_path
            )

            if existing:

                print(
                    f"Found group: {full_path}"
                )

                parent_id = existing["id"]

                continue

            print(
                f"Creating group: {full_path}"
            )

            created = self.gitlab.create_group(
                name=group,
                path=group,
                parent_id=parent_id,
            )

            parent_id = created["id"]

        return parent_id

    # ----------------------------------------------------------

    def get(self, groups):
        """
        Return namespace if exists.
        """

        path = "/".join(
            [self.root_group] + groups
        )

        return self.gitlab.find_group(
            path
        )

    # ----------------------------------------------------------

    def exists(self, groups):

        return self.get(groups) is not None
