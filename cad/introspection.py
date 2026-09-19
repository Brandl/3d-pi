"""Read-only, revision-bound navigation derived from declarative source and reports.

Logical interfaces are generator metadata, not extra exported solids or released
library instances. IDs are stable within a design while names remain unchanged.
"""

import ast


def tree(row):
    document = row["document"]
    parameters = document.get("parameters", {})
    report = (row.get("result") or {}).get("report", {})
    measured = report.get("parts", {})

    def refs(value):
        found = set()
        if isinstance(value, str):
            try:
                found = {
                    n.id for n in ast.walk(ast.parse(value, mode="eval")) if isinstance(n, ast.Name)
                } & parameters.keys()
            except SyntaxError:
                pass
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in {
                    "name",
                    "op",
                    "profile",
                    "inputs",
                    "color",
                    "feature",
                    "material",
                    "edges",
                }:
                    found |= refs(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                found |= refs(item)
        return found

    def parameter_keys(source):
        found = refs(source)
        for _ in range(len(parameters)):
            expanded = found | set().union(*(refs(parameters[key]) for key in found))
            if expanded == found:
                break
            found = expanded
        return sorted(found)

    def node(id, name, kind, source=None, **extra):
        return {
            "id": id,
            "name": name,
            "kind": kind,
            "parameter_keys": parameter_keys(source),
            "children": [],
            **extra,
        }

    features = {f["name"]: f for f in document["features"]}
    feature_nodes = [
        node(
            "feature:" + f["name"],
            f["name"],
            "source_feature",
            f,
            source_path="/features/" + str(i),
            operation=f["op"],
            depends_on=["feature:" + name for name in f.get("inputs", [])],
        )
        for i, f in enumerate(document["features"])
    ]
    parts = []
    for output in document["outputs"]:
        source = features[output["feature"]]
        # Include upstream feature parameters without duplicating the feature DAG.
        pending = [output["feature"]]
        dependencies = set()
        while pending:
            name = pending.pop()
            if name in dependencies:
                continue
            dependencies.add(name)
            pending.extend(features[name].get("inputs", []))
        definition = [features[name] for name in sorted(dependencies)]
        if document.get("solid_master"):
            definition += [document["solid_master"], document.get("casting_box")]
        parts.append(
            node(
                "part:" + output["name"],
                output["name"],
                "part",
                definition,
                output_name=output["name"],
                depends_on=["feature:" + source["name"]],
                measured=output["name"] in measured,
            )
        )
    box = document.get("casting_box")
    joints = []
    if box:
        generator_source = [box, document.get("solid_master"), document["features"]]
        for name in ["wall_left", "wall_right", "lock_front", "lock_back"]:
            part = node(
                "part:" + name,
                name,
                "part",
                generator_source,
                output_name=name,
                source_path="/casting_box",
                measured=name in measured,
            )
            if name.startswith("wall"):
                part["children"] = [
                    node(
                        f"interface:{name}:{end}_rail",
                        end + " rail",
                        "integrated_interface",
                        generator_source,
                        owner="part:" + name,
                        separately_exported=False,
                    )
                    for end in ["front", "back"]
                ]
                if document.get("captured_base"):
                    part["children"].append(
                        node(
                            "interface:" + name + ":floor_channel",
                            "Captured-floor channel",
                            "integrated_interface",
                            generator_source,
                            owner="part:" + name,
                            separately_exported=False,
                        )
                    )
            parts.append(part)
        for end in ["front", "back"]:
            joints.append(
                node(
                    "joint:slide_lock_" + end,
                    end.title() + " slide-lock joint",
                    "mating_relationship",
                    generator_source,
                    members=[
                        f"part:lock_{end}",
                        f"interface:wall_left:{end}_rail",
                        f"interface:wall_right:{end}_rail",
                    ],
                    instructions=[
                        "Slide the capped clip onto the aligned rails; remove it before separating the walls.",
                        "Clearance is normal to mating faces. The loaded cap stop has zero nominal gap.",
                        "Check engagement and removal space after changing wall height. Physical strength is unverified.",
                    ],
                )
            )
        if document.get("captured_base"):
            master = parts[0]
            flange = node(
                "interface:master:floor_flange",
                "Floor flange / retaining shoulder",
                "integrated_interface",
                generator_source,
                owner=master["id"],
                separately_exported=False,
            )
            master["children"].append(flange)
            joints.append(
                node(
                    "joint:captured_floor",
                    "Captured-floor joint",
                    "mating_relationship",
                    generator_source,
                    members=[
                        flange["id"],
                        "interface:wall_left:floor_channel",
                        "interface:wall_right:floor_channel",
                    ],
                    instructions=[
                        "Seat the floor fully before fitting the slide locks. Loaded lower seat has zero nominal gap.",
                        "Check roof-overhang supports, dry-fit and water-test. Leak-tightness and strength are unverified.",
                    ],
                )
            )
    # Legacy generators may add outputs that are not declared in document.outputs.
    known = {part["output_name"] for part in parts}
    for name in sorted(measured.keys() - known):
        parts.append(
            node(
                "part:" + name,
                name,
                "part",
                document,
                output_name=name,
                measured=True,
                provenance="Generated report output; no registered mating metadata",
            )
        )
    root = node("assembly", document["name"], "assembly", document)
    root["children"] = [
        node("parts", "Output parts", "group"),
        node("features", "Source features", "group"),
        node("joints", "Mating relationships", "group"),
    ]
    for group, children in zip(root["children"], [parts, feature_nodes, joints]):
        group["children"] = children
    return {
        "revision": row["id"],
        "status": row["status"],
        "units": "mm",
        "tree_schema_version": 1,
        "metadata_version": 1,
        "basis": "Immutable revision source/reports plus current registered generator metadata; this tree is derived, not a stored geometry artifact",
        "dependency_precision": "Conservative source-scope references; generated parts may share parameters without every parameter changing each part. Not symbolic sensitivity analysis.",
        "component_versions": "No installed library versions: these are design-local parts/features and logical mating relationships.",
        "root": root,
    }


def component(row, component_id):
    structure = tree(row)
    nodes = []

    def visit(node):
        nodes.append(node)
        for child in node["children"]:
            visit(child)

    visit(structure["root"])
    selected = next((n for n in nodes if n["id"] == component_id), None)
    if selected is None:
        raise KeyError(component_id)
    report = (row.get("result") or {}).get("report", {})
    owned = {selected["id"]}
    pending = list(selected["children"])
    while pending:
        child = pending.pop()
        owned.add(child["id"])
        pending.extend(child["children"])
    return {
        "revision": row["id"],
        "status": row["status"],
        "node": selected,
        "parameters": {
            key: {
                "expression": row["document"]["parameters"][key],
                "resolved": report.get("parameters", {}).get(key),
                "used_by": [n["id"] for n in nodes if key in n["parameter_keys"]],
            }
            for key in selected["parameter_keys"]
        },
        "relationships": [
            n for n in nodes if owned.intersection(n.get("members", []) + n.get("depends_on", []))
        ],
        "measurements": report.get("parts", {}).get(selected.get("output_name")),
        "note": "Parameters are design-global. used_by lists conservative source-scope consumers, not proven geometric sensitivity. Interfaces are not separately measured solids.",
    }
