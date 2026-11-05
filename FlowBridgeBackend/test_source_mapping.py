from source_mapping import SourceMappingLayer


mock_mapping_output = {
    "projectId": "p001",
    "projectName": "StudentGrades",
    "sourceMappings": [
        {
            "graphId": "g_fn_check",
            "nodeId": "c_condition",
            "location": {
                "fileId": "f002",
                "startLine": 2,
                "endLine": 2,
                "startColumn": 7,
                "endColumn": 18,
            },
        },
        {
            "graphId": "g_fn_check",
            "nodeId": "c_pass",
            "location": {
                "fileId": "f002",
                "startLine": 3,
                "endLine": 3,
                "startColumn": 8,
                "endColumn": 21,
            },
        },
    ],
}


mapping_layer = SourceMappingLayer()

mapping_layer.loadMappingOutput(mock_mapping_output)

print("Condition mapping:")
print(
    mapping_layer.findSourceMapping(
        "g_fn_check",
        "c_condition"
    )
)

print("\nCondition source location:")
print(
    mapping_layer.getSourceLocation(
        "g_fn_check",
        "c_condition"
    )
)

print("\nMissing node:")
print(
    mapping_layer.getSourceLocation(
        "g_fn_check",
        "does_not_exist"
    )
)
