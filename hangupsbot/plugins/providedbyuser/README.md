# Provided By User

This plugin implements dynamic command registration for each category of user
 data. Users can set their entry or lookup other users entries with a query by
 user or by value.

Note: While categories are case insensitive, Labels are not.

## User Commands 
|               Command                 |               Comment                 |
|               ---                     |               ---                     |
| `/bot setCATEGORY VALUE`              | Add or Update an entry                |
| `/bot deleteCATEGORY`                 | Delete an entry                       |
| `/bot CATEGORY USERNAME` |Get the entries of the users matching the given name|
| `/bot CATEGORY VALUE`    | Search for users having set this `VALUE`           |


## Admin Commands

|               Command                 |               Comment                 |
|               ---                     |               ---                     |
| `/bot providedbyuser add CATEGORY LABEL` | Add a new category `CATEGORY` with the optional label `LABEL`|
| `/bot providedbyuser delete CATEGORY` | Delete the category `CATEGORY`        |
| `/bot providedbyuser list`            | List all added categories             |
| `/bot providedbyuser show CATEGORY`   | Show the entries of the given category|


## Example
One could add a `timezone` category:

```
/bot providedbyuser add timezone
```

- Users can now add their `timezone` entry via

    ```
    /bot settimezone TIMEZONE
    [Joe Doe]: /bot settimezone GMT+2
    [Jane Doe]: /bot settimezone GMT+1
    ```

- Search for entries:

    ```
    /bot search GMT+2
        - Joe Doe:
            GMT+2

    /bot search Doe
        - Joe Doe:
            GMT+2
        - Jane Doe:
            GMT+1
    ```

- Delete their entry:

    ```
    /bot deletetimezone
    ```
