from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ValveNode:
    id: str
    road_name: str = ""
    status: str = "UNKNOWN"       # OPEN | CLOSED | UNKNOWN
    elevation: int = 0
    diameter: int = 0

    @classmethod
    def from_neo4j_record(cls, record: Any) -> "ValveNode":
        d = dict(record)
        return cls(
            id=d.get("id", ""),
            road_name=d.get("road_name", ""),
            status=d.get("status", "UNKNOWN"),
            elevation=int(d.get("elevation", 0)),
            diameter=int(d.get("diameter", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "road_name": self.road_name,
            "status": self.status,
            "elevation": self.elevation,
            "diameter": self.diameter,
        }


@dataclass
class PipeRelationship:
    pipe_id: str
    from_id: str
    to_id: str
    diameter_mm: float = 0.0
    length_m: float = 0.0
    material: str = ""
    status: str = ""
    road_name: str = ""
    year_installed: int = 0
    pressure_mRL: float = 0.0

    @classmethod
    def from_neo4j_record(cls, record: Any) -> "PipeRelationship":
        d = dict(record)
        return cls(
            pipe_id=d.get("pipe_id", ""),
            from_id=d.get("from_id", ""),
            to_id=d.get("to_id", ""),
            diameter_mm=float(d.get("diameter_mm", 0.0)),
            length_m=float(d.get("length_m", 0.0)),
            material=d.get("material", ""),
            status=d.get("status", ""),
            road_name=d.get("road_name", ""),
            year_installed=int(d.get("year_installed", 0)),
            pressure_mRL=float(d.get("pressure_mRL", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipe_id": self.pipe_id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "diameter_mm": self.diameter_mm,
            "length_m": self.length_m,
            "material": self.material,
            "status": self.status,
            "road_name": self.road_name,
            "year_installed": self.year_installed,
            "pressure_mRL": self.pressure_mRL,
        }


@dataclass
class JunctionNode:
    junction_id: str
    x: float = 0.0
    y: float = 0.0
    elevation: float = 0.0
    road_name: str = ""

    @classmethod
    def from_neo4j_record(cls, record: Any) -> "JunctionNode":
        d = dict(record)
        return cls(
            junction_id=d.get("junction_id", ""),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            elevation=float(d.get("elevation", 0.0)),
            road_name=d.get("road_name", ""),
        )


@dataclass
class TankNode:
    id: str
    elevation: float = 0.0

    @classmethod
    def from_neo4j_record(cls, record: Any) -> "TankNode":
        d = dict(record)
        return cls(
            id=d.get("id", ""),
            elevation=float(d.get("elevation", 0.0)),
        )
