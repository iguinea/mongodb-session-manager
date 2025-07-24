from enum import Enum


# Case Types Enum
class CaseType(str, Enum):
    NEW_CLIENT = "New Client"
    NEW_CASE = "New Case"
    NEW_CASE_TYPE = "New Case Type"
    NEW_CASE_STATUS = "New Case Status"

    @classmethod
    def list_values(cls):
        """Return a list of all case type values"""
        return [case.value for case in cls]
