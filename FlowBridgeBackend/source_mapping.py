from typing import List, Optional

from .models import SourceLocation, SourceMapping


class SourceMappingLayer:
    def __init__(self):
        self.sourceMappings: List[SourceMapping] = []
        self.selectedGraphId: Optional[str] = None
        self.selectedNodeId: Optional[str] = None

    def loadMappingOutput(self, output: dict) -> None:
        source_mappings = output.get("sourceMappings", [])
        self.updateMappings(source_mappings)

    def updateMappings(self, source_mappings: list) -> None:
        self.sourceMappings = []

        for mapping in source_mappings:
            location_data = mapping["location"]

            location = SourceLocation(
                fileId=location_data["fileId"],
                startLine=location_data["startLine"],
                endLine=location_data["endLine"],
                startColumn=location_data["startColumn"],
                endColumn=location_data["endColumn"],
            )

            self.sourceMappings.append(
                SourceMapping(
                    graphId=mapping["graphId"],
                    nodeId=mapping["nodeId"],
                    location=location,
                )
            )

    def findSourceMapping(
        self,
        graphId: str,
        nodeId: str,
    ) -> Optional[SourceMapping]:
        for mapping in self.sourceMappings:
            if mapping.graphId == graphId and mapping.nodeId == nodeId:
                return mapping

        return None

    def getSourceLocation(
        self,
        graphId: str,
        nodeId: str,
    ) -> Optional[SourceLocation]:
        mapping = self.findSourceMapping(graphId, nodeId)

        if mapping is None:
            return None

        return mapping.location
