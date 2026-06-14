def add(x, y):
  return x + y

def subtract(x, y):
  return x - y

def multiply(x, y):
  return x * y

def divide(x, y):
  if y == 0:
    return 'Error: Division by zero'
  else:
    return x / y

# Minimal additions to take input and print the result
num1 = float(input("Enter first number: "))
num2 = float(input("Enter second number: "))

print("Add:", add(num1, num2))
print("Subtract:", subtract(num1, num2))
print("Multiply:", multiply(num1, num2)) # Note: fixed to call function properly
print("Divide:", divide(num1, num2))
