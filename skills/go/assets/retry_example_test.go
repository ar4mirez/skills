package retry_test

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/acme/retry"
)

func ExampleDo() {
	attempts := 0
	err := retry.Do(context.Background(), retry.Policy{Attempts: 3, Base: time.Millisecond, Max: 10 * time.Millisecond},
		func(context.Context) error {
			attempts++
			if attempts < 3 {
				return errors.New("temporarily unavailable")
			}
			return nil
		})
	fmt.Println(attempts, err)
	// Output: 3 <nil>
}

func ExamplePermanent() {
	err := retry.Do(context.Background(), retry.Default, func(context.Context) error {
		return retry.Permanent(errors.New("invalid API key"))
	})
	fmt.Println(err)
	// Output: invalid API key
}
