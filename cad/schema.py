"""Versioned, bounded CAD documents. No eval, Python source, or filesystem inputs."""

import ast
import math
import operator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$")]
Scalar = Annotated[float, Field(strict=True)] | Annotated[str, Field(max_length=160)]
Vec = tuple[Scalar, Scalar, Scalar]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class GentleTwist(Strict):
    profile: Literal["cosine", "origami"] = "cosine"
    """Cosine-fluted cone with analytically normal-offset, plane-trimmed interior."""

    height: Scalar
    bottom_radius: Scalar
    top_radius: Scalar
    bottom_amplitude: Scalar
    top_amplitude: Scalar
    flute_count: Scalar
    twist_degrees: Scalar
    wall_thickness: Scalar
    angular_samples: int = Field(default=360, ge=120, le=720)
    vertical_intervals: int = Field(default=128, ge=16, le=256)


class Feature(Strict):
    name: Name
    op: Literal[
        "box",
        "cylinder",
        "sphere",
        "cone",
        "extrude",
        "extrude_z",
        "union",
        "subtract",
        "intersect",
        "fillet",
        "transform",
        "gentle_twist",
    ]
    surface: GentleTwist | None = None
    size: tuple[Scalar, Scalar, Scalar] | None = Field(
        default=None,
        description="Box: X/Y/Z lengths. Cone: bottom radius, top radius, height; Z starts at zero.",
    )
    radius: Scalar | None = None
    height: Scalar | None = None
    points: Annotated[list[tuple[Scalar, Scalar]], Field(min_length=3, max_length=512)] | None = (
        None
    )
    inputs: Annotated[list[Name], Field(max_length=32)] = []
    position: Vec = (0, 0, 0)
    rotation: Vec = (0, 0, 0)
    edges: Literal["all", "parallel_x", "parallel_y", "parallel_z"] = "all"

    @model_validator(mode="after")
    def operands(self):
        required = {
            "box": ["size"],
            "cylinder": ["radius", "height"],
            "sphere": ["radius"],
            "cone": ["size"],
            "extrude": ["points", "height"],
            "extrude_z": ["points", "height"],
            "fillet": ["radius"],
            "gentle_twist": ["surface"],
        }
        for field in required.get(self.op, []):
            if getattr(self, field) is None:
                raise ValueError(f"{self.op} requires {field}")
        counts = {
            "transform": (1, 1),
            "fillet": (1, 1),
            "union": (2, 32),
            "subtract": (2, 32),
            "intersect": (2, 32),
        }
        lo, hi = counts.get(self.op, (0, 0))
        if not lo <= len(self.inputs) <= hi:
            raise ValueError(f"{self.op} requires {lo}..{hi} inputs")
        allowed = set(required.get(self.op, []))
        for field in ("size", "radius", "height", "points", "surface"):
            if getattr(self, field) is not None and field not in allowed:
                raise ValueError(f"{field} is not used by {self.op}")
        if self.op != "fillet" and self.edges != "all":
            raise ValueError("edges is only used by fillet")
        return self


class Output(Strict):
    name: Name
    feature: Name
    color: Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")] = "#71b7d5"
    material: Literal["standard", "porcelain"] = "standard"


class Section(Strict):
    name: Name
    part: Name
    z: Scalar


class Check(Strict):
    part: Name
    metric: Literal["x", "y", "z", "volume", "solid_count"]
    expected: Scalar
    tolerance: Annotated[float, Field(ge=0, le=100)] = 0.001


class CastingBox(Strict):
    """Two outer formwork halves and two slide-down dovetail clips."""

    profile: Literal["rectangular", "round"] = "rectangular"
    plaster_clearance: Scalar = 20
    wall_thickness: Scalar = 4
    top_clearance: Scalar = 20
    rail_depth: Scalar = 8
    rail_half_width: Scalar = 8
    rail_top_margin: Scalar = 8
    rail_bottom_chamfer: Scalar = 0
    lock_wall: Scalar = 3
    lock_clearance: Scalar = 0.3
    lock_length: Scalar = 80


class SolidMaster(Strict):
    """Filled dripper, top collar and lipped base as one continuous solid."""

    wide_end_down: bool = False
    collar_radius: Scalar = 68
    collar_height: Scalar = 20
    base_thickness: Scalar = 4
    base_overhang: Scalar = 4
    lip_height: Scalar = 4
    lip_thickness: Scalar = 3
    lip_clearance: Scalar = 0.3
    capture_normal_clearance: Scalar | None = None
    plaster_corner_chamfer: Scalar = 0
    pedestal_base_chamfer: Scalar = 0
    capture_shoulder: Scalar = 0
    tip_extension: Scalar = 0
    tip_transition: Scalar = 3
    tip_radius: Scalar = 14


class Document(Strict):
    schema_version: Literal[1] = 1
    name: Annotated[str, Field(min_length=1, max_length=120)] = "Untitled model"
    units: Literal["mm"] = "mm"
    parameters: dict[Name, Scalar] = {}
    casting_box: CastingBox | None = None
    solid_master: SolidMaster | None = None
    base_lock: bool = False
    captured_base: bool = False
    features: Annotated[list[Feature], Field(min_length=1, max_length=100)]
    outputs: Annotated[list[Output], Field(min_length=1, max_length=16)]
    sections: Annotated[list[Section], Field(max_length=16)] = []
    checks: Annotated[list[Check], Field(max_length=64)] = []
    linear_tolerance: Annotated[float, Field(ge=0.01, le=1)] = 0.1
    angular_tolerance: Annotated[float, Field(ge=0.05, le=0.8)] = 0.2

    @model_validator(mode="after")
    def references(self):
        if len(self.parameters) > 64:
            raise ValueError("At most 64 parameters")
        if sum(len(f.points or []) for f in self.features) > 2048:
            raise ValueError("At most 2048 total profile points per document")
        known = set()
        for f in self.features:
            if f.name in known:
                raise ValueError(f"Duplicate feature {f.name}")
            if not set(f.inputs) <= known:
                raise ValueError(f"{f.name}: inputs must refer to earlier features")
            known.add(f.name)
        if any(f.op == "gentle_twist" for f in self.features):
            if len(self.features) != 1 or len(self.outputs) != 1 or self.sections:
                raise ValueError("gentle_twist requires one feature/output and no DXF sections")
            f = self.features[0]
            if f.position != (0, 0, 0) or f.rotation != (0, 0, 0):
                raise ValueError(
                    "gentle_twist is axis-aligned at the origin; placements are not supported"
                )
        if self.casting_box:
            if len(self.features) != 1 or self.features[0].op != "gentle_twist":
                raise ValueError(
                    "Casting-box tooling currently requires the gentle_twist reference"
                )
            if self.outputs[0].name in {"wall_left", "wall_right", "lock_front", "lock_back"}:
                raise ValueError("Output name conflicts with a generated tooling component")
        if self.solid_master and (not self.casting_box or self.casting_box.profile != "round"):
            raise ValueError("Solid master requires round casting-box tooling")
        if self.captured_base and (
            self.base_lock or not self.solid_master or not self.solid_master.wide_end_down
        ):
            raise ValueError(
                "Captured dry base requires a wide-end-down master and no screw-clamp kit"
            )
        if self.base_lock and (not self.solid_master or not self.solid_master.wide_end_down):
            raise ValueError("Base locks require a wide-end-down solid master")
        if self.base_lock and (
            self.outputs[0].name == "base_gasket"
            or self.outputs[0].name.startswith(("base_clamp_", "m5_"))
        ):
            raise ValueError("Output name conflicts with base-lock components")
        names = [p.name for p in self.outputs]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate output names")
        if any(p.feature not in known for p in self.outputs):
            raise ValueError("Output references unknown feature")
        if len({s.name for s in self.sections}) != len(self.sections):
            raise ValueError("Duplicate section names")
        if any(s.part not in names for s in [*self.sections, *self.checks]):
            raise ValueError("Section/check references unknown output")
        return self


class Expressions:
    """Only finite arithmetic and named parameters. No calls, access, powers or eval."""

    def __init__(self, parameters):
        self.parameters = parameters
        self.resolved = {}
        self.active = set()
        for name in parameters:
            self.parameter(name)

    def parameter(self, name):
        if name in self.resolved:
            return self.resolved[name]
        if name not in self.parameters or name in self.active:
            raise ValueError(f"Unknown or cyclic parameter: {name}")
        self.active.add(name)
        result = self.value(self.parameters[name])
        self.active.remove(name)
        self.resolved[name] = result
        return result

    def value(self, source):
        if isinstance(source, (float, int)) and not isinstance(source, bool):
            result = float(source)
        else:
            tree = ast.parse(source, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise ValueError("Expression is too complex")
            result = self.node(tree.body)
        if not math.isfinite(result) or abs(result) > 1e9:
            raise ValueError("Expression must be finite and within +/- 1e9")
        return result

    def node(self, node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return self.value(node.value)
        if isinstance(node, ast.Name):
            return self.parameter(node.id)
        ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
        }
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return self.value(ops[type(node.op)](self.node(node.left), self.node(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return self.node(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise ValueError("Only numbers, parameters, +, -, *, / and parentheses are allowed")
