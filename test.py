import random

# 生成10个随机数，放入数组当中
numbers = []
for i in range(10):
    numbers.append(random.randint(1, 100))

# 遍历数组打印
print("生成的10个随机数：")
for num in numbers:
    print(num)
