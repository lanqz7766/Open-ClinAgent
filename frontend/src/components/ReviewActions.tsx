import { Button } from "@/components/ui/button"

type ReviewActionsProps = {
  onApprove: () => void
  onReject: () => void
  onAcknowledge?: () => void
  status?: string
  comment?: string
}

export function ReviewActions({
  comment,
  onAcknowledge,
  onApprove,
  onReject,
  status,
}: ReviewActionsProps) {
  return (
    <div className="space-y-3">
      {status || comment ? (
        <div className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] p-3">
          {status ? <p className="text-[12px] text-[hsl(var(--muted-foreground))]">Status: {status}</p> : null}
          {comment ? <p className="mt-1 text-[13px] text-[hsl(var(--foreground))]">{comment}</p> : null}
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {onAcknowledge ? (
          <Button className="h-8" onClick={onAcknowledge} variant="outline">
            Acknowledge
          </Button>
        ) : null}
        <Button className="h-8" onClick={onReject} variant="outline">
          Reject
        </Button>
        <Button className="h-8" onClick={onApprove}>
          Approve
        </Button>
      </div>
    </div>
  )
}
