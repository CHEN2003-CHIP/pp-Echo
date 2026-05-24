from __future__ import annotations


class TreeNode:
    def __init__(self, val: int = 0, left: "TreeNode | None" = None, right: "TreeNode | None" = None) -> None:
        self.val = val
        self.left = left
        self.right = right


def sumNumbers(root: TreeNode | None) -> int:
    def dfs(node: TreeNode | None, current: int) -> int:
        if node is None:
            return 0
        current = current * 10 + node.val
        if node.left is None and node.right is None:
            return current
        return dfs(node.left, current) + dfs(node.right, current)

    return dfs(root, 0)


if __name__ == "__main__":
    # Example 1: [1,2,3] -> 12 + 13 = 25
    root1 = TreeNode(1, TreeNode(2), TreeNode(3))
    print(sumNumbers(root1))

    # Example 2: [4,9,0,5,1] -> 495 + 491 + 40 = 1026
    root2 = TreeNode(
        4,
        TreeNode(9, TreeNode(5), TreeNode(1)),
        TreeNode(0),
    )
    print(sumNumbers(root2))
