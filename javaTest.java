/**
 * LeetCode 236: 二叉树的最近公共祖先
 * 
 * 给定一个二叉树, 找到该树中两个指定节点的最近公共祖先。
 * 
 * 最近公共祖先的定义为："对于有根树 T 的两个节点 p、q，最近公共祖先表示为一个节点 x，
 * 满足 x 是 p、q 的祖先且 x 的深度尽可能大（一个节点也可以是它自己的祖先）。"
 */

// 二叉树节点定义
class TreeNode {
    int val;
    TreeNode left;
    TreeNode right;
    
    TreeNode(int x) {
        val = x;
    }
}

public class javaTest {
    
    /**
     * 方法一：递归法
     * 
     * 思路：
     * 1. 如果当前节点为空，或者等于 p 或 q，直接返回当前节点
     * 2. 递归在左子树和右子树中查找 p 和 q
     * 3. 如果左右子树都找到了节点，说明当前节点就是最近公共祖先
     * 4. 如果只有一边找到，返回找到的那一边的结果
     * 
     * 时间复杂度：O(n)，其中 n 是树的节点数
     * 空间复杂度：O(h)，其中 h 是树的高度（递归栈的深度）
     */
    public TreeNode lowestCommonAncestor(TreeNode root, TreeNode p, TreeNode q) {
        // 基本情况：如果根节点为空，或者根节点就是 p 或 q，直接返回根节点
        if (root == null || root == p || root == q) {
            return root;
        }
        
        // 在左子树中查找 p 或 q
        TreeNode left = lowestCommonAncestor(root.left, p, q);
        
        // 在右子树中查找 p 或 q
        TreeNode right = lowestCommonAncestor(root.right, p, q);
        
        // 如果左右子树都找到了节点，说明当前节点是最近公共祖先
        if (left != null && right != null) {
            return root;
        }
        
        // 如果只有一边找到，返回找到的那一边的结果
        return left != null ? left : right;
    }
    
    /**
     * 辅助方法：用于测试，构建一个简单的二叉树
     *       3
     *      / \
     *     5   1
     *    / \ / \
     *   6  2 0  8
     *     / \
     *    7   4
     */
    public TreeNode buildSampleTree() {
        TreeNode root = new TreeNode(3);
        root.left = new TreeNode(5);
        root.right = new TreeNode(1);
        root.left.left = new TreeNode(6);
        root.left.right = new TreeNode(2);
        root.right.left = new TreeNode(0);
        root.right.right = new TreeNode(8);
        root.left.right.left = new TreeNode(7);
        root.left.right.right = new TreeNode(4);
        return root;
    }
    
    /**
     * 辅助方法：查找值为 val 的节点
     */
    public TreeNode findNode(TreeNode root, int val) {
        if (root == null) {
            return null;
        }
        if (root.val == val) {
            return root;
        }
        TreeNode left = findNode(root.left, val);
        if (left != null) {
            return left;
        }
        return findNode(root.right, val);
    }
    
    /**
     * 主方法：测试代码
     */
    public static void main(String[] args) {
        javaTest solution = new javaTest();
        
        // 构建示例树
        TreeNode root = solution.buildSampleTree();
        
        // 测试用例 1: 节点 5 和节点 1 的最近公共祖先应该是 3
        TreeNode p1 = solution.findNode(root, 5);
        TreeNode q1 = solution.findNode(root, 1);
        TreeNode lca1 = solution.lowestCommonAncestor(root, p1, q1);
        System.out.println("测试 1 - 节点 5 和节点 1 的最近公共祖先: " + 
                          (lca1 != null ? lca1.val : "null"));
        // 预期输出: 3
        
        // 测试用例 2: 节点 5 和节点 4 的最近公共祖先应该是 5
        TreeNode p2 = solution.findNode(root, 5);
        TreeNode q2 = solution.findNode(root, 4);
        TreeNode lca2 = solution.lowestCommonAncestor(root, p2, q2);
        System.out.println("测试 2 - 节点 5 和节点 4 的最近公共祖先: " + 
                          (lca2 != null ? lca2.val : "null"));
        // 预期输出: 5
        
        // 测试用例 3: 节点 7 和节点 4 的最近公共祖先应该是 2
        TreeNode p3 = solution.findNode(root, 7);
        TreeNode q3 = solution.findNode(root, 4);
        TreeNode lca3 = solution.lowestCommonAncestor(root, p3, q3);
        System.out.println("测试 3 - 节点 7 和节点 4 的最近公共祖先: " + 
                          (lca3 != null ? lca3.val : "null"));
        // 预期输出: 2
        
        System.out.println("\n所有测试完成！");
    }
}
