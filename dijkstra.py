import heapq
import itertools


def dijkstra(graph, source, destination):
    """
    Find the minimum-travel-time path using Dijkstra's algorithm.

    graph format:
        {
            "H": [("A", 4), ("B", 2)],
            ...
        }

    Returns:
        (path, total_time)
        If no route exists, returns (None, infinity).
    """
    distance = {node: float("inf") for node in graph}
    parent = {node: None for node in graph}

    distance[source] = 0
    min_heap = [(0, source)]

    while min_heap:
        current_distance, current_node = heapq.heappop(min_heap)

        # Skip old entries if a shorter distance was found later.
        if current_distance > distance[current_node]:
            continue

        if current_node == destination:
            break

        for neighbor, travel_time in graph[current_node]:
            new_distance = current_distance + travel_time

            if new_distance < distance[neighbor]:
                distance[neighbor] = new_distance
                parent[neighbor] = current_node
                heapq.heappush(min_heap, (new_distance, neighbor))

    if distance[destination] == float("inf"):
        return None, float("inf")

    # Rebuild the path by walking backwards from destination.
    path = []
    current_node = destination

    while current_node is not None:
        path.append(current_node)
        current_node = parent[current_node]

    path.reverse()
    return path, distance[destination]


def shortest_alternative_route(graph, source, destination, shortest_path):
    """Return the fastest distinct loopless path after the shortest path."""
    routes = k_shortest_routes(graph, source, destination, limit=2)
    if len(routes) < 2:
        return None, float("inf")
    return routes[1]


def k_shortest_routes(graph, source, destination, limit=3):
    """Return up to ``limit`` distinct, loopless paths in travel-time order."""
    if limit <= 0:
        return []

    shortest_path, shortest_duration = dijkstra(graph, source, destination)
    if shortest_path is None:
        return []

    accepted = [(shortest_path, shortest_duration)]
    candidates = []
    candidate_paths = set()
    sequence = itertools.count()

    while len(accepted) < limit:
        previous_path = accepted[-1][0]
        for spur_index in range(len(previous_path) - 1):
            root_path = previous_path[: spur_index + 1]
            spur_node = root_path[-1]
            filtered_graph = {
                node: list(edges) for node, edges in graph.items()
            }

            for accepted_path, _ in accepted:
                if (
                    len(accepted_path) > spur_index + 1
                    and accepted_path[: spur_index + 1] == root_path
                ):
                    first = accepted_path[spur_index]
                    second = accepted_path[spur_index + 1]
                    filtered_graph[first] = [
                        (neighbor, weight)
                        for neighbor, weight in filtered_graph[first]
                        if neighbor != second
                    ]
                    filtered_graph[second] = [
                        (neighbor, weight)
                        for neighbor, weight in filtered_graph[second]
                        if neighbor != first
                    ]

            for root_node in root_path[:-1]:
                filtered_graph[root_node] = []
                for node in filtered_graph:
                    filtered_graph[node] = [
                        (neighbor, weight)
                        for neighbor, weight in filtered_graph[node]
                        if neighbor != root_node
                    ]

            spur_path, _ = dijkstra(filtered_graph, spur_node, destination)
            if spur_path is None:
                continue
            combined_path = root_path[:-1] + spur_path
            path_key = tuple(combined_path)
            if path_key in candidate_paths or any(
                tuple(path) == path_key for path, _ in accepted
            ):
                continue

            total_duration = sum(
                next(
                    weight
                    for neighbor, weight in graph[first]
                    if neighbor == second
                )
                for first, second in zip(combined_path, combined_path[1:])
            )
            heapq.heappush(
                candidates,
                (total_duration, next(sequence), combined_path),
            )
            candidate_paths.add(path_key)

        if not candidates:
            break
        duration, _, path = heapq.heappop(candidates)
        candidate_paths.discard(tuple(path))
        accepted.append((path, duration))

    return accepted
