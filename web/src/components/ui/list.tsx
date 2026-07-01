import * as React from "react";
import { cn } from "@/lib/utils";

const List = React.forwardRef<HTMLUListElement, React.HTMLAttributes<HTMLUListElement>>(({ className, ...props }, ref) => (
  <ul ref={ref} className={cn("space-y-2", className)} {...props} />
));
List.displayName = "List";

const ListItem = React.forwardRef<HTMLLIElement, React.LiHTMLAttributes<HTMLLIElement>>(({ className, ...props }, ref) => (
  <li ref={ref} className={cn("flex items-center justify-between gap-3 text-sm", className)} {...props} />
));
ListItem.displayName = "ListItem";

export { List, ListItem };
